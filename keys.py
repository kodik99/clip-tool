"""API keys: environment variable first, then the OS keychain (service 'memeclip'; 'autoclip' too for the Anthropic key)."""
import os

ENV_VARS = {"anthropic": "ANTHROPIC_API_KEY", "groq": "GROQ_API_KEY"}
SERVICES = {"anthropic": ("memeclip", "autoclip"), "groq": ("memeclip",)}


def get_secret(name):
    v = os.environ.get(ENV_VARS[name])
    if v:
        return v
    try:
        import keyring
    except ImportError:
        return None
    for service in SERVICES[name]:
        try:
            v = keyring.get_password(service, name)
            if v:
                return v
        except Exception:
            pass
    return None
