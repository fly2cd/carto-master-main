"""Allowlisted provider diagnostics and host recovery actions; no upstream text."""


def classify_amap_error(code):
    if code in {'10004', '10014', '10015', '10019', '10020', '10021', 'HTTP_429'}:
        return {'error_category': 'rate_limit', 'retryable': True, 'suggested_action': 'wait_and_resume',
                'message': 'Amap rate limit reached. Keep the task, reduce request rate, then resume.'}
    if code in {'10003', '10044', '10045', '40000', '40003'}:
        scope = 'overseas daily account quota (10045)' if code == '10045' else 'account/key usage quota or balance'
        return {'error_category': 'quota_exhausted', 'retryable': False, 'suggested_action': 'check_account_quota',
                'message': 'Amap ' + scope + ' is exhausted. Check the account quota/billing before resuming. '
                           'This is a provider rejection, not evidence that the place is missing. '
                           'Do not replace the place, estimate coordinates, or recreate/delete its project.'}
    if code in {'10001', '10009', '10013'}:
        return {'error_category': 'authentication', 'retryable': False, 'suggested_action': 'check_credentials',
                'message': 'Check the configured Web-service key and platform binding, then resume the same task.'}
    if code in {'10002', '10012', '10041', '40002'}:
        return {'error_category': 'permission', 'retryable': False, 'suggested_action': 'check_permissions',
                'message': 'Check Amap service permission or expiry, then resume the same task.'}
    if code in {'TIMEOUT', 'NETWORK_ERROR', 'HTTP_408'}:
        return {'error_category': 'network', 'retryable': True, 'suggested_action': 'wait_and_resume',
                'message': 'Network request failed. Preserve the checkpoint and resume after connectivity recovers.'}
    if code in {'INVALID_RESPONSE', '10016', '10017'} or code.startswith('HTTP_5'):
        return {'error_category': 'upstream', 'retryable': True, 'suggested_action': 'wait_and_resume',
                'message': 'The provider is temporarily unavailable. Preserve the task and resume later.'}
    if code in {'20000', '20001', '20002'}:
        return {'error_category': 'invalid_request', 'retryable': False, 'suggested_action': 'check_request',
                'message': 'Check the provider request parameters; do not guess a replacement location.'}
    return {'error_category': 'unknown', 'retryable': False, 'suggested_action': 'check_provider',
            'message': 'Inspect the provider error code and service configuration before resuming.'}
