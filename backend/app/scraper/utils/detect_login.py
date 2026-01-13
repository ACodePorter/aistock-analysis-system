"""
登录页面检测模块

检测响应是否为登录页面或需要登录的页面
遵循以下规则避免误检:
1. 重定向检测: 检查是否有重定向到登录页
2. 状态码检测: 401/403 且包含登录相关关键词
3. 表单检测: 检查是否有密码输入框 + 登录相关文本
4. 网站特定规则: 为天眼查/企查查等写特征规则
5. 内容长度异常: 极短内容（可能被拦截）
"""

import re
from typing import Tuple
from urllib.parse import urlparse


# 强登录指示 - 必须有实际登录形式的表单
STRONG_LOGIN_INDICATORS = [
    r'<form[^>]*>.*?<input[^>]*password[^>]*>',  # 包含密码字段的表单
    r'<input[^>]*name=["\']password["\']?',       # 密码输入框
    r'<input[^>]*id=["\']password["\']?',         # ID为password的输入框
    r'</form>\s*.*?<input[^>]*captcha',           # 包含验证码的表单
]

# 弱登录指示 - 登录相关文字（需要和其他条件结合）
WEAK_LOGIN_INDICATORS = [
    r'请先登录',
    r'请登录后查看',
    r'需要登录',
    r'账号密码登录',
    r'验证码',
    r'扫码登录',
]

# 登录表单字段
LOGIN_FORM_FIELDS = [
    r'name=["\']?password["\']?',
    r'name=["\']?username["\']?',
    r'name=["\']?email["\']?',
    r'name=["\']?captcha["\']?',
    r'name=["\']?verify["\']?',
    r'id=["\']?password["\']?',
    r'id=["\']?captcha["\']?',
]

# 网站特定的登录页特征
SITE_SPECIFIC_LOGIN_PATTERNS = {
    'tianyancha.com': [
        r'扫码登录天眼查',
        r'账号登录天眼查',
        r'天眼查会员',
        r'请登录后查看详情',
        r'登录后可查看',
    ],
    'qcc.com': [
        r'企查查会员',
        r'扫码登录',
        r'账号密码登录',
        r'请登录后查看',
        r'登录后可查看',
    ],
}

# 白名单 - 这些网站不应该被检测为登录页
WHITELIST_DOMAINS = [
    'wikipedia.org',
    'en.wikipedia.org',
    'zh.wikipedia.org',
    'commons.wikimedia.org',
]



def is_login_page(
    response_text: str,
    response_headers: dict,
    url: str,
    status_code: int = 200
) -> Tuple[bool, str]:
    """
    判断响应是否为登录页面 - 改进算法，避免误检
    
    Args:
        response_text: 响应体文本
        response_headers: 响应头字典
        url: 请求的URL
        status_code: HTTP状态码
        
    Returns:
        (is_login, reason): 是否为登录页, 原因说明
    """
    
    # 检查0: 白名单 - 这些网站不应该被标记为登录
    if is_whitelisted_domain(url):
        return False, "Domain is whitelisted (e.g., Wikipedia)"
    
    # 检查1: HTTP状态码
    if status_code in [401, 403]:
        # 401/403 只有在包含实际登录表单或强烈登录指示时才标记
        if has_strong_login_form(response_text):
            return True, f"HTTP {status_code} with strong login form"
        if contains_strong_login_indicators(response_text):
            return True, f"HTTP {status_code} with strong login indicators"
        # 否则不确定
        return False, f"HTTP {status_code} but no strong login indicators"
    
    if status_code >= 500:
        return False, f"Server error {status_code}"
    
    # 检查2: 重定向URL中的登录标志
    location_header = response_headers.get('Location', '').lower()
    if location_header:
        if any(keyword in location_header for keyword in [
            'login', 'signin', 'passport', 'captcha', 'verify', 'auth'
        ]):
            return True, f"Redirect to login page: {location_header}"
    
    # 检查3: 网站特定规则（高优先级）
    domain = extract_domain(url)
    if domain in SITE_SPECIFIC_LOGIN_PATTERNS:
        for pattern in SITE_SPECIFIC_LOGIN_PATTERNS[domain]:
            if re.search(pattern, response_text, re.IGNORECASE):
                return True, f"Site-specific login pattern matched: {pattern}"
    
    # 检查4: 强登录指示（密码表单 + 登录文本的组合）
    if has_strong_login_form(response_text):
        return True, "Strong login form detected (password field + login form)"
    
    # 检查5: 使用强登录指示器
    if contains_strong_login_indicators(response_text):
        # 但需要排除一些误检情况
        if should_exclude_login_detection(response_text, url):
            return False, "Has login keywords but excluded by rules"
        return True, "Strong login indicators found"
    
    # 检查6: 内容长度异常（极短内容但非错误页）
    if status_code == 200 and response_text:
        text_len = len(response_text.strip())
        if text_len < 100 and ("登录" in response_text or "login" in response_text.lower()):
            return True, f"Suspiciously short response ({text_len} bytes) with login keywords"
    
    return False, "Not a login page"


def is_whitelisted_domain(url: str) -> bool:
    """检查域名是否在白名单中"""
    try:
        domain = extract_domain(url)
        for whitelisted in WHITELIST_DOMAINS:
            if whitelisted in domain or domain.endswith(whitelisted.replace('www.', '')):
                return True
    except:
        pass
    return False


def contains_strong_login_indicators(text: str) -> bool:
    """检查是否包含强登录指示"""
    if not text:
        return False
    
    strong_count = 0
    
    # 检查强指示器
    for pattern in STRONG_LOGIN_INDICATORS:
        if re.search(pattern, text, re.IGNORECASE | re.DOTALL):
            return True
    
    # 检查弱指示器数量（至少2个）
    for pattern in WEAK_LOGIN_INDICATORS:
        if re.search(pattern, text):
            strong_count += 1
    
    return strong_count >= 2


def has_strong_login_form(text: str) -> bool:
    """检查是否有强登录表单（密码字段 + 表单组合）"""
    if not text:
        return False
    
    has_form = '<form' in text.lower()
    has_password = any(
        re.search(field, text, re.IGNORECASE) 
        for field in LOGIN_FORM_FIELDS if 'password' in field
    )
    
    return has_form and has_password


def should_exclude_login_detection(response_text: str, url: str) -> bool:
    """
    检查是否应该排除登录检测（避免误检）
    例如维基百科包含登录链接但不是登录页
    """
    # 维基百科特殊处理
    if 'wikipedia' in url.lower():
        # 维基百科页面虽然可能包含"编辑"、"登录"链接，
        # 但如果有主要内容（大量文本），则不是登录页
        if len(response_text) > 5000:
            return True
        if '==' in response_text and ']]' in response_text:  # wiki标记
            return True
    
    return False


def extract_domain(url: str) -> str:
    """从URL中提取域名"""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # 去掉www前缀进行匹配
        domain = domain.replace('www.', '')
        return domain
    except:
        return ""


def get_login_detection_metadata(
    response_text: str,
    response_headers: dict,
    url: str
) -> dict:
    """
    获取登录检测的详细元数据（用于日志）
    
    Returns:
        dict包含检测到的各项指标
    """
    metadata = {
        'url': url,
        'status_code': response_headers.get('status', 'unknown'),
        'has_strong_login_form': has_strong_login_form(response_text),
        'has_strong_indicators': contains_strong_login_indicators(response_text),
        'has_form_fields': any(
            re.search(field, response_text, re.IGNORECASE) 
            for field in LOGIN_FORM_FIELDS
        ),
        'redirect_location': response_headers.get('Location', ''),
        'response_snippet': response_text[:500] if response_text else '',
        'response_length': len(response_text) if response_text else 0,
    }
    return metadata


# ==================== 单元测试用例 ====================

def test_detect_login():
    """运行登录检测测试"""
    test_cases = [
        # (response_text, headers, url, status_code, expected_is_login, description)
        
        # Wikipedia不应该被检测为登录
        (
            '<h1>阿里巴巴</h1><p>阿里巴巴集团控股有限公司（简称：阿里巴巴）...长度>5000</p>' + 'x'*5000,
            {},
            'https://zh.wikipedia.org/wiki/阿里巴巴',
            200,
            False,
            "Wikipedia with content should not be detected as login"
        ),
        
        # 天眼查登录页面
        (
            '<div>扫码登录天眼查</div><form><input name="password"/></form>',
            {},
            'https://www.tianyancha.com/login',
            200,
            True,
            "Tianyancha login page with specific pattern"
        ),
        
        # 企查查登录页面
        (
            '<div>企查查会员</div><form><input name="password"/><input name="username"/></form>',
            {},
            'https://www.qcc.com/login',
            200,
            True,
            "QCC login page with password form"
        ),
        
        # 403 without login form
        (
            '<h1>403 Forbidden</h1>',
            {},
            'https://example.com/protected',
            403,
            False,
            "403 without login form should not be marked as login"
        ),
        
        # 401 with login keywords and form
        (
            '<form><input name="password"/></form>请先登录',
            {},
            'https://example.com/api',
            401,
            True,
            "401 with login form and keywords"
        ),
        
        # Redirect to login
        (
            '<p>redirecting...</p>',
            {'Location': 'https://example.com/login'},
            'https://example.com/page',
            302,
            True,
            "Redirect to login page"
        ),
    ]
    
    results = []
    for text, headers, url, status, expected, desc in test_cases:
        is_login, reason = is_login_page(text, headers, url, status)
        passed = is_login == expected
        results.append({
            'description': desc,
            'passed': passed,
            'expected': expected,
            'got': is_login,
            'reason': reason,
        })
        print(f"{'✅' if passed else '❌'} {desc}")
        if not passed:
            print(f"   Expected: {expected}, Got: {is_login}, Reason: {reason}")
    
    return results

