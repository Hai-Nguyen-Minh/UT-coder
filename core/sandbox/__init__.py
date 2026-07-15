from .base import SandboxResult, Sandbox
from .python_sandbox import PythonSandbox
from .csharp_sandbox import CSharpSandbox
from .java_sandbox import JavaSandbox
from .js_sandbox import JavascriptSandbox

def get_sandbox(language: str) -> Sandbox:
    """Factory method to get the appropriate sandbox for a language."""
    language = language.lower()
    if language == "python":
        return PythonSandbox()
    elif language == "csharp":
        return CSharpSandbox()
    elif language == "java":
        return JavaSandbox()
    elif language in ("javascript", "js", "typescript", "ts"):
        return JavascriptSandbox()
    # Fallback to a stub sandbox for unimplemented languages for now
    return Sandbox()
