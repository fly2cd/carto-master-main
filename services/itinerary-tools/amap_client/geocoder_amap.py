"""Amap lookup with consistent ambiguity checks and bounded transport retries."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import os
import re

import httpx
from .amap_rate_limit import wait_for_amap_slot

from .coord_converter import CoordConverter
from .ambiguity_checker import (
    check_amap_pois, GeoAmbiguityError, MultiGeoAmbiguityError, MAX_CANDIDATES_FETCH,
)


class GeocodingProviderError(RuntimeError):
    """Only allowlisted diagnostic fields may cross the provider boundary."""

    def __init__(self, diagnostics):
        self.diagnostics = deepcopy(diagnostics)
        super().__init__('Geocoding provider request failed; inspect sanitized diagnostics.')


class AmapGeocoder:
    GEOCODE_URL = 'https://restapi.amap.com/v3/geocode/geo'
    POI_SEARCH_URL = 'https://restapi.amap.com/v3/place/text'
    # Official Amap transient QPS / busy / resource-unavailable codes.
    TRANSIENT_CODES = {'10004', '10014', '10015', '10016', '10017',
                       '10019', '10020', '10021'}
    TRANSIENT_INFO = {'ACCESS_TOO_FREQUENT', 'QPS_HAS_EXCEEDED_THE_LIMIT',
                      'GATEWAY_TIMEOUT', 'SERVER_IS_BUSY', 'RESOURCE_UNAVAILABLE',
                      'CQPS_HAS_EXCEEDED_THE_LIMIT', 'CKQPS_HAS_EXCEEDED_THE_LIMIT',
                      'CUQPS_HAS_EXCEEDED_THE_LIMIT'}

    def __init__(self, amap_key: str = ''):
        self.amap_key = amap_key or os.environ.get('CARTO_AMAP_KEY', '')
        self.diagnostics = []
        self._location_index = 1
        self._cache = {}
        self._attempts = {}

    def _event(self, stage, attempt, outcome, code):
        self.diagnostics.append({'location_index': self._location_index,
            'stage': stage, 'attempt': attempt, 'outcome': outcome, 'code': code})

    async def _request(self, client, url, params, stage, max_retries):
        attempts = max(1, min(int(max_retries), 3))
        for attempt in range(1, attempts + 1):
            self._attempts[stage] = attempt
            retryable = False
            try:
                await wait_for_amap_slot()
                response = await client.get(url, params=params, timeout=10.0)
                if response.status_code != 200:
                    code = f'HTTP_{response.status_code}'
                    retryable = response.status_code in {408, 429, 500, 502, 503, 504}
                else:
                    try:
                        data = response.json()
                    except ValueError:
                        data = None
                    if not isinstance(data, dict):
                        code, retryable = 'INVALID_RESPONSE', True
                    elif data.get('status') == '1':
                        self._event(stage, attempt, 'succeeded', '10000')
                        return data
                    else:
                        raw_code = str(data.get('infocode', ''))
                        # Do not echo arbitrary upstream info, URLs or response bodies.
                        code = raw_code if re.fullmatch(r'[0-9]{5}', raw_code) else 'API_ERROR'
                        retryable = (raw_code in self.TRANSIENT_CODES
                                     or data.get('info') in self.TRANSIENT_INFO)
            except httpx.TimeoutException:
                code, retryable = 'TIMEOUT', True
            except httpx.TransportError:
                code, retryable = 'NETWORK_ERROR', True
            if retryable and attempt < attempts:
                self._event(stage, attempt, 'retry', code)
                await asyncio.sleep(0.5 * 2 ** (attempt - 1))
                continue
            self._event(stage, attempt, 'failed', code)
            raise GeocodingProviderError(self.diagnostics) from None

    def _checked(self, name, city, pois, count, stage):
        attempt = self._attempts.get(stage, 1)
        try:
            report = check_amap_pois(name, city, pois, int(count or 0))
        except (ValueError, TypeError, KeyError, IndexError):
            self._event(stage, attempt, 'failed', 'INVALID_RESPONSE')
            raise GeocodingProviderError(self.diagnostics) from None
        if report.verdict in {'block', 'warn'}:
            self._event(stage, attempt, 'ambiguous', 'USER_CONFIRMATION_REQUIRED')
            raise GeoAmbiguityError(report)
        chosen = report.candidates[0]
        if not CoordConverter.is_valid_china_coord(chosen.lon, chosen.lat):
            self._event(stage, attempt, 'failed', 'INVALID_COORDINATES')
            raise GeocodingProviderError(self.diagnostics)
        return round(chosen.lon, 6), round(chosen.lat, 6), chosen.address or chosen.name

    async def geocode_single(self, client, name, city='', max_retries=3):
        """Return GCJ-02; fall back only on a successful POI response with no hits."""
        key = (name, city)
        if key in self._cache:
            self._event('cache', 1, 'cache_hit', 'SUCCESS_CACHE')
            return self._cache[key]
        params = {'key': self.amap_key, 'keywords': name, 'extensions': 'base',
                  'offset': MAX_CANDIDATES_FETCH, 'page': 1}
        if city:
            params.update(city=city, citylimit='true')
        data = await self._request(client, self.POI_SEARCH_URL, params, 'poi_search', max_retries)
        if data.get('pois'):
            result = self._checked(name, city, data['pois'], data.get('count'), 'poi_search')
        else:
            self._event('poi_search', self._attempts['poi_search'], 'no_results', 'NO_RESULTS')
            params = {'key': self.amap_key, 'address': name}
            if city:
                params['city'] = city
            data = await self._request(client, self.GEOCODE_URL, params, 'geocoding', max_retries)
            pois = [{'name': gc.get('formatted_address', name),
                     'address': gc.get('formatted_address', ''), 'location': gc.get('location', ''),
                     'cityname': gc.get('city', ''), 'adname': gc.get('district', ''), 'id': None}
                    for gc in data.get('geocodes', [])]
            result = self._checked(name, city, pois, data.get('count'), 'geocoding')
        # Ambiguous, failed and user-supplied coordinates are never search-cache entries.
        self._cache[key] = result
        return result

    async def geocode_batch(self, client, locations, convert_to_wgs84=True):
        points, reports = [], []
        for idx, item in enumerate(locations):
            self._location_index = idx + 1
            name, city = item.get('name', ''), item.get('city', '')
            if item.get('_confirmed_lon') is not None and item.get('_confirmed_lat') is not None:
                raw_lon, raw_lat = float(item['_confirmed_lon']), float(item['_confirmed_lat'])
                address = name
            else:
                try:
                    raw_lon, raw_lat, address = await self.geocode_single(client, name, city)
                except GeoAmbiguityError as exc:
                    reports.append(exc.report)
                    await asyncio.sleep(0.12)
                    continue
            lon, lat = (CoordConverter.gcj02_to_wgs84(raw_lon, raw_lat)
                        if convert_to_wgs84 else (raw_lon, raw_lat))
            point = {'id': f'point_{idx + 1:03}', 'name': name, 'formattedAddress': address,
                     'lon': lon, 'lat': lat, '_raw_lon': raw_lon, '_raw_lat': raw_lat, 'order': idx + 1}
            if 'place_id' in item:
                point['place_id'] = item['place_id']
            points.append(point)
            await asyncio.sleep(0.12)
        if reports:
            raise MultiGeoAmbiguityError(reports, partial_points=points)
        return points
