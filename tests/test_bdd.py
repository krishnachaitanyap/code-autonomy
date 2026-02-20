"""Tests for src/bdd/ — JISI BDD service spec, prompt builder, output parser."""

import json
import os
import tempfile

import pytest

from src.bdd.service_spec import ServiceSpec, Operation, FieldDefinition
from src.bdd.prompt_builder import build_jisi_bdd_prompt, _filter_primitive_fields
from src.bdd.output_parser import BDDOutputBundle, parse_bdd_output, validate_bdd_files


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _sample_spec_dict():
    """Return a minimal valid spec dict."""
    return {
        "service_name": "AccountLookupRESTSvc",
        "endpoint": "/profilecore/services/AccountLookup",
        "team": "GWS-ProfileCore",
        "application_tag": "GWS",
        "test_types": ["regression", "compare", "pvt", "heartbeat"],
        "operations": [
            {
                "name": "getAccountDetails",
                "path": "/profilecore/services/AccountLookup/getAccountDetails",
                "method": "POST",
                "request_fields": [
                    {"name": "accountNumber", "type": "String", "required": True},
                    {"name": "accountType", "type": "String"},
                ],
                "response_fields": [
                    {"name": "accountId", "type": "String"},
                    {"name": "balance", "type": "BigDecimal"},
                    {"name": "status", "type": "String"},
                ],
            }
        ],
    }


def _sample_spec() -> ServiceSpec:
    return ServiceSpec.from_dict(_sample_spec_dict())


# ---------------------------------------------------------------------------
# ServiceSpec.from_dict
# ---------------------------------------------------------------------------

class TestServiceSpecFromDict:
    def test_basic_fields(self):
        spec = _sample_spec()
        assert spec.service_name == "AccountLookupRESTSvc"
        assert spec.endpoint == "/profilecore/services/AccountLookup"
        assert spec.team == "GWS-ProfileCore"
        assert spec.application_tag == "GWS"
        assert spec.base_class == "ServiceBase"

    def test_operations_parsed(self):
        spec = _sample_spec()
        assert len(spec.operations) == 1
        op = spec.operations[0]
        assert op.name == "getAccountDetails"
        assert op.method == "POST"
        assert len(op.request_fields) == 2
        assert len(op.response_fields) == 3

    def test_request_field_required(self):
        spec = _sample_spec()
        op = spec.operations[0]
        assert op.request_fields[0].required is True
        assert op.request_fields[1].required is False

    def test_test_types(self):
        spec = _sample_spec()
        assert spec.test_types == ["regression", "compare", "pvt", "heartbeat"]

    def test_defaults(self):
        data = {
            "service_name": "TestSvc",
            "endpoint": "/test",
            "operations": [],
        }
        spec = ServiceSpec.from_dict(data)
        assert spec.team == ""
        assert spec.application_tag == "GWS"
        assert spec.base_class == "ServiceBase"
        assert spec.test_types == ["regression"]


# ---------------------------------------------------------------------------
# ServiceSpec.from_file
# ---------------------------------------------------------------------------

class TestServiceSpecFromFile:
    def test_load_json(self, tmp_path):
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(json.dumps(_sample_spec_dict()))
        spec = ServiceSpec.from_file(str(spec_file))
        assert spec.service_name == "AccountLookupRESTSvc"
        assert len(spec.operations) == 1

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            ServiceSpec.from_file("/nonexistent/spec.json")

    def test_example_file_loads(self):
        """Verify the shipped example spec is valid."""
        example = os.path.join(os.path.dirname(__file__), "..", "examples", "bdd_spec_example.json")
        if os.path.exists(example):
            spec = ServiceSpec.from_file(example)
            assert spec.service_name == "AccountLookupRESTSvc"
            assert spec.validate() == []


# ---------------------------------------------------------------------------
# ServiceSpec.validate
# ---------------------------------------------------------------------------

class TestServiceSpecValidate:
    def test_valid_spec_no_errors(self):
        spec = _sample_spec()
        assert spec.validate() == []

    def test_missing_service_name(self):
        data = _sample_spec_dict()
        data["service_name"] = ""
        spec = ServiceSpec.from_dict(data)
        errors = spec.validate()
        assert any("service_name" in e for e in errors)

    def test_missing_endpoint(self):
        data = _sample_spec_dict()
        data["endpoint"] = ""
        spec = ServiceSpec.from_dict(data)
        errors = spec.validate()
        assert any("endpoint" in e for e in errors)

    def test_no_operations(self):
        data = _sample_spec_dict()
        data["operations"] = []
        spec = ServiceSpec.from_dict(data)
        errors = spec.validate()
        assert any("operation" in e for e in errors)

    def test_unsupported_method(self):
        data = _sample_spec_dict()
        data["operations"][0]["method"] = "OPTIONS"
        spec = ServiceSpec.from_dict(data)
        errors = spec.validate()
        assert any("unsupported method" in e for e in errors)

    def test_unsupported_test_type(self):
        data = _sample_spec_dict()
        data["test_types"] = ["regression", "foobar"]
        spec = ServiceSpec.from_dict(data)
        errors = spec.validate()
        assert any("foobar" in e for e in errors)


# ---------------------------------------------------------------------------
# _filter_primitive_fields
# ---------------------------------------------------------------------------

class TestFilterPrimitiveFields:
    def test_keeps_primitives(self):
        fields = [
            FieldDefinition("a", "String"),
            FieldDefinition("b", "Integer"),
            FieldDefinition("c", "BigDecimal"),
        ]
        result = _filter_primitive_fields(fields)
        assert len(result) == 3

    def test_filters_complex_types(self):
        fields = [
            FieldDefinition("a", "String"),
            FieldDefinition("b", "AddressDTO"),
            FieldDefinition("c", "List<String>"),
        ]
        result = _filter_primitive_fields(fields)
        assert len(result) == 1
        assert result[0].name == "a"

    def test_empty_list(self):
        assert _filter_primitive_fields([]) == []


# ---------------------------------------------------------------------------
# build_jisi_bdd_prompt
# ---------------------------------------------------------------------------

class TestBuildJisiBddPrompt:
    def test_contains_service_name(self):
        prompt = build_jisi_bdd_prompt(_sample_spec())
        assert "AccountLookupRESTSvc" in prompt

    def test_contains_enterprise_tags(self):
        prompt = build_jisi_bdd_prompt(_sample_spec())
        assert "@Application-GWS" in prompt
        assert "@Service-AccountLookupRESTSvc" in prompt
        assert "@Team-GWS-ProfileCore" in prompt
        assert "@Test-regression" in prompt

    def test_contains_operation_details(self):
        prompt = build_jisi_bdd_prompt(_sample_spec())
        assert "getAccountDetails" in prompt
        assert "POST" in prompt

    def test_contains_critical_rules(self):
        prompt = build_jisi_bdd_prompt(_sample_spec())
        assert "CommonSteps" in prompt
        assert "GenericSteps" in prompt
        assert "ServiceBase" in prompt

    def test_contains_output_markers(self):
        prompt = build_jisi_bdd_prompt(_sample_spec())
        assert "===FEATURE_FILE_START===" in prompt
        assert "===SERVICE_CLASS_START===" in prompt
        assert "===PROPERTY_ENTRY_START===" in prompt

    def test_contains_property_format(self):
        prompt = build_jisi_bdd_prompt(_sample_spec())
        assert "AccountLookupRESTSvc.endpoint=" in prompt

    def test_contains_create_request_methods(self):
        prompt = build_jisi_bdd_prompt(_sample_spec())
        assert "createRequest_getAccountDetails()" in prompt

    def test_filters_complex_fields(self):
        """Complex types should not appear in the operation details."""
        data = _sample_spec_dict()
        data["operations"][0]["request_fields"].append(
            {"name": "address", "type": "AddressDTO"}
        )
        spec = ServiceSpec.from_dict(data)
        prompt = build_jisi_bdd_prompt(spec)
        assert "AddressDTO" not in prompt


# ---------------------------------------------------------------------------
# parse_bdd_output
# ---------------------------------------------------------------------------

class TestParseBddOutput:
    def test_full_parse(self):
        text = (
            "Some preamble\n"
            "===FEATURE_FILE_START===\n"
            "Feature: Test\n"
            "===FEATURE_FILE_END===\n"
            "\n"
            "===SERVICE_CLASS_START===\n"
            "public class TestSvc extends ServiceBase {}\n"
            "===SERVICE_CLASS_END===\n"
            "\n"
            "===PROPERTY_ENTRY_START===\n"
            "TestSvc.endpoint=${${env}.profilecore.ws.url}/test\n"
            "===PROPERTY_ENTRY_END===\n"
        )
        bundle = parse_bdd_output(text)
        assert bundle.is_complete
        assert "Feature: Test" in bundle.feature_file
        assert "ServiceBase" in bundle.service_class
        assert "TestSvc.endpoint=" in bundle.property_entry
        assert bundle.missing_artifacts() == []

    def test_partial_parse(self):
        text = (
            "===FEATURE_FILE_START===\n"
            "Feature: Test\n"
            "===FEATURE_FILE_END===\n"
        )
        bundle = parse_bdd_output(text)
        assert not bundle.is_complete
        assert bundle.feature_file == "Feature: Test"
        assert bundle.service_class == ""
        assert "service_class" in bundle.missing_artifacts()
        assert "property_entry" in bundle.missing_artifacts()

    def test_empty_input(self):
        bundle = parse_bdd_output("")
        assert not bundle.is_complete
        assert len(bundle.missing_artifacts()) == 3


# ---------------------------------------------------------------------------
# validate_bdd_files
# ---------------------------------------------------------------------------

class TestValidateBddFiles:
    def test_all_files_present(self):
        files = [
            "src/test/resources/features/AccountLookupRESTSvc.feature",
            "src/test/java/com/enterprise/test/services/AccountLookupRESTSvc.java",
        ]
        warnings = validate_bdd_files(files, "AccountLookupRESTSvc")
        assert warnings == []

    def test_missing_feature(self):
        files = [
            "src/test/java/com/enterprise/test/services/AccountLookupRESTSvc.java",
        ]
        warnings = validate_bdd_files(files, "AccountLookupRESTSvc")
        assert len(warnings) == 1
        assert "feature" in warnings[0].lower()

    def test_missing_service_class(self):
        files = [
            "src/test/resources/features/AccountLookupRESTSvc.feature",
        ]
        warnings = validate_bdd_files(files, "AccountLookupRESTSvc")
        assert len(warnings) == 1
        assert "class" in warnings[0].lower()

    def test_both_missing(self):
        warnings = validate_bdd_files([], "AccountLookupRESTSvc")
        assert len(warnings) == 2


# ---------------------------------------------------------------------------
# Testing strategy integration
# ---------------------------------------------------------------------------

class TestStrategyIntegration:
    def test_jisi_bdd_in_strategies(self):
        from src.code.testing_strategies import STRATEGIES
        assert "jisi_bdd" in STRATEGIES

    def test_jisi_bdd_in_guidance(self):
        from src.code.testing_strategies import STRATEGY_GUIDANCE
        assert "jisi_bdd" in STRATEGY_GUIDANCE
        meta = STRATEGY_GUIDANCE["jisi_bdd"]
        assert "JISI" in meta["name"]
        assert meta["prompt"].strip()

    def test_get_context_jisi_bdd(self):
        from src.code.testing_strategies import get_testing_strategy_context
        ctx = get_testing_strategy_context("jisi_bdd", "maven", "")
        assert "CommonSteps" in ctx
        assert "ServiceBase" in ctx

    def test_auto_detect_jisi(self):
        from src.code.testing_strategies import get_testing_strategy_context
        ctx = get_testing_strategy_context("auto", "maven", "generate jisi bdd tests for servicebase")
        assert "JISI" in ctx or "CommonSteps" in ctx

    def test_auto_detect_commonsteps(self):
        from src.code.testing_strategies import get_testing_strategy_context
        ctx = get_testing_strategy_context("auto", "maven", "use commonsteps and genericsteps")
        assert "ServiceBase" in ctx


# ---------------------------------------------------------------------------
# Config loader integration
# ---------------------------------------------------------------------------

class TestConfigLoaderIntegration:
    def test_parse_bdd_spec_from_changes(self):
        from src.config_loader import parse_bdd_spec_from_changes
        content = "# BDD spec: path/to/spec.json\nGenerate tests"
        assert parse_bdd_spec_from_changes(content) == "path/to/spec.json"

    def test_parse_bdd_spec_not_present(self):
        from src.config_loader import parse_bdd_spec_from_changes
        assert parse_bdd_spec_from_changes("Generate tests") is None

    def test_parse_testing_strategy_jisi_bdd(self):
        from src.config_loader import parse_testing_strategy_from_changes
        content = "# Testing strategy: jisi_bdd\nGenerate tests"
        assert parse_testing_strategy_from_changes(content) == "jisi_bdd"
