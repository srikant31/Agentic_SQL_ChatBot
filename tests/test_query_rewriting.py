import json
from unittest.mock import Mock, patch
import pytest
from sql_generator import rewrite_question, LLMProviderError


def test_rewriter_receives_original_current_and_all_modifications_without_executing():
    model = Mock()
    model.invoke.return_value.content = json.dumps({"question": "Count Engineering employees by job title."})
    with patch("sql_generator._build_llm", return_value=model), patch("database.run_query") as execute:
        result = rewrite_question("Count employees", "Count Engineering employees", ["Only Engineering", "Group by job title"])
    assert result == "Count Engineering employees by job title."
    payload = json.loads(model.invoke.call_args.args[0][1].content)
    assert payload["modifications"] == ["Only Engineering", "Group by job title"]
    assert payload["original_question"] == "Count employees"
    execute.assert_not_called()


@pytest.mark.parametrize("response", ['{"question": ""}', '[]', 'not JSON', '{"sql":"SELECT 1"}'])
def test_bad_rewrite_output_is_rejected(response):
    model = Mock()
    model.invoke.return_value.content = response
    with patch("sql_generator._build_llm", return_value=model):
        with pytest.raises(RuntimeError):
            rewrite_question("Count employees", "Count employees", ["Only Engineering"])


def test_rewrite_provider_errors_do_not_expose_details():
    with patch("sql_generator._build_llm", side_effect=RuntimeError("private provider detail")):
        with pytest.raises(LLMProviderError) as error:
            rewrite_question("Count employees", "Count employees", ["Only Engineering"])
    assert "private provider detail" not in str(error.value)
