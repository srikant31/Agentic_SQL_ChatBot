"""User-facing query errors without importing either database workflow."""
from sql_generator import LLMProviderError
from safety import SchemaValidationError, UnsafeQueryError
from semantic_validation import SemanticValidationError


def error_message(error):
    if isinstance(error, LLMProviderError):
        return str(error)
    if isinstance(error, (SchemaValidationError, UnsafeQueryError, SemanticValidationError, PermissionError, ValueError)):
        return f"The query could not pass validation: {error}"
    return "The request could not be completed. Check the provider or connection, or describe your modifications."
