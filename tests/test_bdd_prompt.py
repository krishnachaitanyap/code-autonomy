"""Tests for the updated JISI BDD prompt builder with exact ServiceBase patterns."""

import pytest

from src.bdd.service_spec import ServiceSpec, Operation, FieldDefinition, _class_to_path
from src.bdd.prompt_builder import build_jisi_bdd_prompt, _filter_primitive_fields


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _full_spec_dict():
    """Return a spec dict that exercises all new ServiceBase fields."""
    return {
        "service_name": "ListByAccountsProfileAccountRESTSvc",
        "endpoint": "/profilecore/services/ProfileAccount/listByAccounts",
        "team": "GWS-ProfileCore",
        "application_tag": "GWS",
        "base_class": "ServiceBase",
        "package_name": "com.cig.gws.profilecore",
        "feature_name": "ListByAccountsProfileAccount",
        "response_type_name": "ProfileAccount",
        "domain": "profilecore",
        "channel_types": ["C30"],
        "user_types": ["PR"],
        "test_types": ["regression", "end_to_end", "pvt", "compare"],
        "operations": [
            {
                "name": "listByAccounts",
                "path": "/profilecore/services/ProfileAccount/listByAccounts",
                "method": "POST",
                "request_fields": [
                    {"name": "accountId", "type": "String", "required": True},
                ],
                "response_fields": [
                    {"name": "profileAccountType", "type": "String"},
                    {"name": "accountId", "type": "String"},
                ],
                "account_types": ["CHK", "SAV"],
                "response_fields_map": {
                    "PROFILE_ACCOUNT_TYPE": "profileAccountType",
                    "ACCOUNT_ID": "accountId",
                },
                "request_payload_fields": [],
                "test_types": ["regression", "end_to_end", "pvt", "compare"],
            }
        ],
    }


def _full_spec() -> ServiceSpec:
    return ServiceSpec.from_dict(_full_spec_dict())


def _minimal_spec_dict():
    """Minimal spec — uses all defaults for new fields."""
    return {
        "service_name": "AccountLookupRESTSvc",
        "endpoint": "/profilecore/services/AccountLookup",
        "team": "GWS-ProfileCore",
        "operations": [
            {
                "name": "getAccountDetails",
                "path": "/profilecore/services/AccountLookup/getAccountDetails",
                "method": "POST",
            }
        ],
    }


def _minimal_spec() -> ServiceSpec:
    return ServiceSpec.from_dict(_minimal_spec_dict())


def _multi_op_spec_dict():
    """Spec with multiple operations to test multi-op prompt generation."""
    return {
        "service_name": "MultiOpRESTSvc",
        "endpoint": "/services/MultiOp",
        "team": "GWS-Team",
        "domain": "gateway",
        "test_types": ["regression", "pvt"],
        "operations": [
            {
                "name": "getDetails",
                "path": "/services/MultiOp/getDetails",
                "method": "POST",
                "account_types": ["CHK"],
                "response_fields_map": {"STATUS": "status"},
            },
            {
                "name": "updateDetails",
                "path": "/services/MultiOp/updateDetails",
                "method": "PUT",
                "account_types": ["SAV", "CHK"],
                "response_fields_map": {"RESULT": "result"},
                "test_types": ["regression", "end_to_end"],
            },
        ],
    }


def _multi_op_spec() -> ServiceSpec:
    return ServiceSpec.from_dict(_multi_op_spec_dict())


# ---------------------------------------------------------------------------
# ServiceSpec new fields
# ---------------------------------------------------------------------------

class TestServiceSpecNewFields:
    def test_new_defaults(self):
        spec = _minimal_spec()
        assert spec.package_name == "com.enterprise.test.services"
        assert spec.feature_name == ""
        assert spec.response_type_name == ""
        assert spec.domain == "profilecore"
        assert spec.channel_types == ["C30"]
        assert spec.user_types == ["PR"]

    def test_full_spec_fields(self):
        spec = _full_spec()
        assert spec.package_name == "com.cig.gws.profilecore"
        assert spec.feature_name == "ListByAccountsProfileAccount"
        assert spec.response_type_name == "ProfileAccount"
        assert spec.domain == "profilecore"

    def test_operation_new_defaults(self):
        spec = _minimal_spec()
        op = spec.operations[0]
        assert op.account_types == ["CHK", "SAV"]
        assert op.response_fields_map == {}
        assert op.request_payload_fields == []
        assert op.test_types == []

    def test_operation_full_fields(self):
        spec = _full_spec()
        op = spec.operations[0]
        assert op.account_types == ["CHK", "SAV"]
        assert "PROFILE_ACCOUNT_TYPE" in op.response_fields_map
        assert op.response_fields_map["PROFILE_ACCOUNT_TYPE"] == "profileAccountType"
        assert op.test_types == ["regression", "end_to_end", "pvt", "compare"]

    def test_validate_end_to_end_type(self):
        spec = _full_spec()
        assert spec.validate() == []

    def test_validate_empty_package_name(self):
        data = _full_spec_dict()
        data["package_name"] = ""
        spec = ServiceSpec.from_dict(data)
        errors = spec.validate()
        assert any("package_name" in e for e in errors)

    def test_validate_empty_domain(self):
        data = _full_spec_dict()
        data["domain"] = ""
        spec = ServiceSpec.from_dict(data)
        errors = spec.validate()
        assert any("domain" in e for e in errors)

    def test_validate_empty_channel_types(self):
        data = _full_spec_dict()
        data["channel_types"] = []
        spec = ServiceSpec.from_dict(data)
        errors = spec.validate()
        assert any("channel_type" in e for e in errors)

    def test_validate_empty_user_types(self):
        data = _full_spec_dict()
        data["user_types"] = []
        spec = ServiceSpec.from_dict(data)
        errors = spec.validate()
        assert any("user_type" in e for e in errors)

    def test_validate_op_bad_test_type(self):
        data = _full_spec_dict()
        data["operations"][0]["test_types"] = ["regression", "badtype"]
        spec = ServiceSpec.from_dict(data)
        errors = spec.validate()
        assert any("badtype" in e for e in errors)


# ---------------------------------------------------------------------------
# Feature file patterns in prompt
# ---------------------------------------------------------------------------

class TestPromptFeatureFile:
    def test_heartbeat_scenario_present(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "HealthCheck_profilecore" in prompt
        assert "@Test-heartbeat" in prompt

    def test_heartbeat_is_first_scenario(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        hb_pos = prompt.index("HealthCheck_")
        # Scenario Outline should come after heartbeat
        so_pos = prompt.index("Scenario Outline:")
        assert hb_pos < so_pos

    def test_feature_level_tags(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "@Application-GWS" in prompt
        assert "@Service-ListByAccountsProfileAccountRESTSvc" in prompt
        assert "@Team-GWS-ProfileCore" in prompt

    def test_scenario_outline_with_examples(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "Scenario Outline:" in prompt
        assert "Examples:" in prompt
        assert "| channelType | userType | accountType |" in prompt
        assert "C30" in prompt
        assert "CHK" in prompt
        assert "SAV" in prompt

    def test_common_steps_verbs(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "Given A <channelType> user" in prompt
        assert "And with <userType> user" in prompt
        assert "And with <accountType> account" in prompt
        assert "When I request for listByAccounts" in prompt
        assert "Then it should not contain Errors" in prompt

    def test_response_field_validation_steps(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "it should return PROFILE_ACCOUNT_TYPE information in ProfileAccount response" in prompt
        assert "it should return ACCOUNT_ID information in ProfileAccount response" in prompt

    def test_per_test_type_scenarios(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "@Test-regression" in prompt
        assert "@Test-end_to_end" in prompt
        assert "@Test-pvt" in prompt
        assert "@Test-compare" in prompt

    def test_operation_tags(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "@Operation-listByAccounts" in prompt

    def test_feature_name_used(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "Feature: ListByAccountsProfileAccount" in prompt

    def test_feature_name_fallback(self):
        prompt = build_jisi_bdd_prompt(_minimal_spec())
        assert "Feature: AccountLookupRESTSvc" in prompt


# ---------------------------------------------------------------------------
# Service class patterns in prompt
# ---------------------------------------------------------------------------

class TestPromptServiceClass:
    def test_extends_service_base(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "extends ServiceBase" in prompt

    def test_package_declaration(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "package com.cig.gws.profilecore;" in prompt

    def test_imports(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "import com.cig.gws.ServiceBase;" in prompt
        assert "import cucumber.api.java.en.And;" in prompt
        assert "import cucumber.api.java.en.Then;" in prompt
        assert "import org.json.simple.JSONArray;" in prompt
        assert "import org.json.simple.JSONObject;" in prompt
        assert "import org.junit.Assert;" in prompt
        assert "import java.util.HashMap;" in prompt
        assert "import java.util.Set;" in prompt
        assert "import java.util.HashSet;" in prompt

    def test_static_field_set(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "protected static final Set<String>" in prompt
        assert 'add("PROFILE_ACCOUNT_TYPE");' in prompt
        assert 'add("ACCOUNT_ID");' in prompt

    def test_create_request_method(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "createRequest_listByAccounts()" in prompt
        assert "HashMap<String, Object> createRequest = new HashMap<>()" in prompt
        assert "JSONObject payload = new JSONObject()" in prompt
        assert "requestResponse.setRequest(createRequest)" in prompt

    def test_service_base_helper_calls(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "this.getDefaultUser().getAccount().getAccountId()" in prompt
        assert "this.getDefaultRestRequestContext()" in prompt
        assert "this.getDefaultUser().getProfileId()" in prompt
        assert "this.getEndPoint()" in prompt

    def test_then_and_annotations(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert '@Then("^it should contain' in prompt
        assert '@And("^it should return (.*) information in' in prompt

    def test_assert_patterns(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "Assert.assertTrue" in prompt
        assert "Assert.assertNotNull" in prompt

    def test_check_data_element_helper(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "checkDataElementInResponse(JSONArray response, String element)" in prompt
        assert "response.get(0)" in prompt

    def test_request_response_bridge(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "requestResponse.setRequest(createRequest)" in prompt
        assert "requestResponse.getResponse()" in prompt

    def test_pvt_variant_method(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "createRequest_listByAccounts_pvt()" in prompt

    def test_compare_variant_method(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "createRequest_listByAccounts_compare()" in prompt

    def test_end_to_end_variant_method(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "createRequest_listByAccounts_end_to_end()" in prompt


# ---------------------------------------------------------------------------
# Property entry
# ---------------------------------------------------------------------------

class TestPromptPropertyEntry:
    def test_property_format(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        expected = (
            "ListByAccountsProfileAccountRESTSvc.endpoint="
            "${${env}.profilecore.ws.url}"
            "/profilecore/services/ProfileAccount/listByAccounts"
        )
        assert expected in prompt

    def test_property_uses_domain(self):
        data = _full_spec_dict()
        data["domain"] = "gateway"
        spec = ServiceSpec.from_dict(data)
        prompt = build_jisi_bdd_prompt(spec)
        assert "${${env}.gateway.ws.url}" in prompt

    def test_minimal_property_format(self):
        prompt = build_jisi_bdd_prompt(_minimal_spec())
        assert "AccountLookupRESTSvc.endpoint=" in prompt
        assert "${${env}.profilecore.ws.url}" in prompt


# ---------------------------------------------------------------------------
# Output markers
# ---------------------------------------------------------------------------

class TestPromptOutputMarkers:
    def test_feature_markers(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "===FEATURE_FILE_START===" in prompt
        assert "===FEATURE_FILE_END===" in prompt

    def test_service_class_markers(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "===SERVICE_CLASS_START===" in prompt
        assert "===SERVICE_CLASS_END===" in prompt

    def test_property_markers(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "===PROPERTY_ENTRY_START===" in prompt
        assert "===PROPERTY_ENTRY_END===" in prompt


# ---------------------------------------------------------------------------
# Multi-operation specs
# ---------------------------------------------------------------------------

class TestPromptMultipleOperations:
    def test_both_operations_in_prompt(self):
        prompt = build_jisi_bdd_prompt(_multi_op_spec())
        assert "getDetails" in prompt
        assert "updateDetails" in prompt

    def test_both_create_request_methods(self):
        prompt = build_jisi_bdd_prompt(_multi_op_spec())
        assert "createRequest_getDetails()" in prompt
        assert "createRequest_updateDetails()" in prompt

    def test_per_op_test_type_override(self):
        """updateDetails has its own test_types — should generate end_to_end but not pvt."""
        prompt = build_jisi_bdd_prompt(_multi_op_spec())
        # updateDetails has test_types=["regression", "end_to_end"]
        assert "createRequest_updateDetails_end_to_end()" in prompt

    def test_op_field_sets_separate(self):
        prompt = build_jisi_bdd_prompt(_multi_op_spec())
        assert 'add("STATUS");' in prompt
        assert 'add("RESULT");' in prompt

    def test_multiple_operation_tags(self):
        prompt = build_jisi_bdd_prompt(_multi_op_spec())
        assert "@Operation-getDetails" in prompt
        assert "@Operation-updateDetails" in prompt

    def test_domain_in_property(self):
        prompt = build_jisi_bdd_prompt(_multi_op_spec())
        assert "${${env}.gateway.ws.url}" in prompt


# ---------------------------------------------------------------------------
# Critical rules section
# ---------------------------------------------------------------------------

class TestPromptCriticalRules:
    def test_heartbeat_first_rule(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "heartbeat scenario first" in prompt

    def test_create_request_pattern_rule(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "HashMap + JSONObject + JSONArray" in prompt

    def test_check_data_element_rule(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "checkDataElementInResponse()" in prompt

    def test_request_response_bridge_rule(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "requestResponse.setRequest(createRequest)" in prompt
        assert "requestResponse.getResponse()" in prompt

    def test_suffix_variant_rule(self):
        prompt = build_jisi_bdd_prompt(_full_spec())
        assert "_pvt" in prompt


# ---------------------------------------------------------------------------
# Backward compatibility — _filter_primitive_fields still works
# ---------------------------------------------------------------------------

class TestFilterPrimitiveFieldsCompat:
    def test_keeps_primitives(self):
        fields = [
            FieldDefinition("a", "String"),
            FieldDefinition("b", "Integer"),
            FieldDefinition("c", "BigDecimal"),
        ]
        assert len(_filter_primitive_fields(fields)) == 3

    def test_filters_complex_types(self):
        fields = [
            FieldDefinition("a", "String"),
            FieldDefinition("b", "AddressDTO"),
        ]
        result = _filter_primitive_fields(fields)
        assert len(result) == 1
        assert result[0].name == "a"


# ---------------------------------------------------------------------------
# Invoker/Handler source file reading in prompt
# ---------------------------------------------------------------------------

def _invoker_handler_spec(**overrides) -> ServiceSpec:
    """Build a spec with invoker/handler class references."""
    data = _minimal_spec_dict()
    data.update(overrides)
    return ServiceSpec.from_dict(data)


class TestPromptInvokerHandler:
    def test_no_invoker_handler_no_section(self):
        """When both are empty, prompt does NOT contain Pre-Generation Step."""
        prompt = build_jisi_bdd_prompt(_minimal_spec())
        assert "Pre-Generation Step" not in prompt

    def test_service_level_invoker_in_prompt(self):
        """When invoker_class is set on ServiceSpec, prompt contains the file path and read instruction."""
        spec = _invoker_handler_spec(
            invoker_class="com.enterprise.services.profilecore.AccountLookupInvoker",
        )
        prompt = build_jisi_bdd_prompt(spec)
        assert "Pre-Generation Step" in prompt
        assert "Invoker (Request DTO)" in prompt
        assert "src/main/java/com/enterprise/services/profilecore/AccountLookupInvoker.java" in prompt

    def test_service_level_handler_in_prompt(self):
        """When handler_class is set on ServiceSpec, prompt contains the file path and read instruction."""
        spec = _invoker_handler_spec(
            handler_class="com.enterprise.services.profilecore.AccountLookupHandler",
        )
        prompt = build_jisi_bdd_prompt(spec)
        assert "Pre-Generation Step" in prompt
        assert "Handler (Response DTO)" in prompt
        assert "src/main/java/com/enterprise/services/profilecore/AccountLookupHandler.java" in prompt

    def test_invoker_path_derived_from_class(self):
        """Fully qualified class name is converted to source file path."""
        spec = _invoker_handler_spec(
            invoker_class="com.enterprise.services.FooInvoker",
        )
        prompt = build_jisi_bdd_prompt(spec)
        assert "src/main/java/com/enterprise/services/FooInvoker.java" in prompt

    def test_handler_path_derived_from_class(self):
        """Fully qualified handler class name is converted to source file path."""
        spec = _invoker_handler_spec(
            handler_class="com.enterprise.services.FooHandler",
        )
        prompt = build_jisi_bdd_prompt(spec)
        assert "src/main/java/com/enterprise/services/FooHandler.java" in prompt

    def test_invoker_extraction_instructions(self):
        """Prompt contains invoker-specific extraction instructions."""
        spec = _invoker_handler_spec(
            invoker_class="com.enterprise.services.FooInvoker",
        )
        prompt = build_jisi_bdd_prompt(spec)
        assert "extract all request fields" in prompt
        assert "payload.put" in prompt

    def test_handler_extraction_instructions(self):
        """Prompt contains handler-specific extraction instructions."""
        spec = _invoker_handler_spec(
            handler_class="com.enterprise.services.FooHandler",
        )
        prompt = build_jisi_bdd_prompt(spec)
        assert "extract all response fields" in prompt
        assert "Set<String>" in prompt
        assert "checkDataElementInResponse()" in prompt

    def test_per_operation_override(self):
        """Operation-level invoker/handler appears in the prompt with operation label."""
        data = _minimal_spec_dict()
        data["operations"][0]["invoker_class"] = "com.enterprise.services.OpInvoker"
        data["operations"][0]["handler_class"] = "com.enterprise.services.OpHandler"
        spec = ServiceSpec.from_dict(data)
        prompt = build_jisi_bdd_prompt(spec)
        assert "Pre-Generation Step" in prompt
        assert "Operation `getAccountDetails`" in prompt
        assert "src/main/java/com/enterprise/services/OpInvoker.java" in prompt
        assert "src/main/java/com/enterprise/services/OpHandler.java" in prompt

    def test_read_file_tool_instruction(self):
        """Prompt mentions read_file tool."""
        spec = _invoker_handler_spec(
            invoker_class="com.enterprise.services.FooInvoker",
        )
        prompt = build_jisi_bdd_prompt(spec)
        assert "read_file" in prompt


class TestClassToPath:
    def test_simple_class(self):
        assert _class_to_path("com.foo.Bar") == "src/main/java/com/foo/Bar.java"

    def test_deep_package(self):
        assert _class_to_path("com.enterprise.services.profilecore.AccountLookupInvoker") == \
            "src/main/java/com/enterprise/services/profilecore/AccountLookupInvoker.java"
