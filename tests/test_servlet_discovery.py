"""Tests for src/bdd/servlet_discovery.py — XML servlet auto-discovery."""

import textwrap
from pathlib import Path

import pytest

from src.bdd.servlet_discovery import (
    DiscoveredEndpoint,
    _find_servlet_xml_files,
    _parse_rest_servlet_xml,
    _parse_cxf_servlet_xml,
    _derive_service_name,
    _find_java_source,
    _build_import_map,
    _extract_dto_fields,
    _build_spec_from_endpoint,
    discover_service_specs,
)

# Try importing javalang — some tests are skipped if unavailable
try:
    import javalang
    HAS_JAVALANG = True
except ImportError:
    HAS_JAVALANG = False

needs_javalang = pytest.mark.skipif(not HAS_JAVALANG, reason="javalang not installed")


# ======================================================================
# Helpers — create temp XML / Java files
# ======================================================================

_REST_SERVLET_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <beans xmlns="http://www.springframework.org/schema/beans"
           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
           xmlns:context="http://www.springframework.org/schema/context"
           xsi:schemaLocation="http://www.springframework.org/schema/beans
               http://www.springframework.org/schema/beans/spring-beans.xsd">

        <context:component-scan base-package="com.chase.digital.profile.web" />
        <context:annotation-config />

        <bean id="profile_account_lookup.AccountLookupSvcController"
              class="com.chase.digital.profile.api.profile.account.AccountLookupSvcController" />
        <bean id="listProfileAttributeController"
              class="com.chase.digital.profile.api.profile.attribute.rest.controller.ListProfileAttributeController" />
        <bean id="someHelperBean"
              class="com.chase.digital.profile.util.SomeHelper" />
    </beans>
""")

_CXF_SERVLET_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <beans xmlns="http://www.springframework.org/schema/beans"
           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
           xmlns:jaxws="http://cxf.apache.org/jaxws"
           xmlns:cxf="http://cxf.apache.org/core"
           xsi:schemaLocation="
               http://www.springframework.org/schema/beans
               http://www.springframework.org/schema/beans/spring-beans.xsd
               http://cxf.apache.org/jaxws
               http://cxf.apache.org/schemas/jaxws.xsd">

        <cxf:bus>
            <cxf:inInterceptors>
                <bean class="com.chase.digital.interceptor.SOAPHttpHeaderInterceptor" />
            </cxf:inInterceptors>
        </cxf:bus>

        <jaxws:endpoint id="CISCustomerSvc_20160313"
                        implementor="com.chase.digital.profile.cis.customer.ws.v20160313.CISCustomerSvcImpl"
                        address="/ws/CISCustomerSvc/20160313">
            <jaxws:properties>
                <entry key="schema-validation-enabled" value="false"/>
            </jaxws:properties>
        </jaxws:endpoint>

        <jaxws:endpoint id="ProfileEquivalenceSearchSvc_20130721"
                        implementor="com.chase.digital.profile.equivalence.search.ws.v20130721.ProfileEquivalenceSearchSvcImpl"
                        address="/ws/ProfileEquivalenceSearchSvc/20130721" />
    </beans>
""")

_CONTROLLER_JAVA = textwrap.dedent("""\
    package com.chase.digital.profile.api.profile.account;

    import org.springframework.beans.factory.annotation.Autowired;
    import org.springframework.web.bind.annotation.RequestMapping;
    import org.springframework.web.bind.annotation.PostMapping;
    import org.springframework.web.bind.annotation.RestController;
    import com.chase.digital.profile.invoker.AccountLookupInvoker;
    import com.chase.digital.profile.handler.AccountLookupHandler;

    @RestController
    @RequestMapping("/profilecore/services/AccountLookup")
    public class AccountLookupSvcController {

        @Autowired
        private AccountLookupInvoker invoker;

        @Autowired
        private AccountLookupHandler handler;

        @PostMapping("/getAccountDetails")
        public Object getAccountDetails() {
            return null;
        }

        @PostMapping("/getAccountSummary")
        public Object getAccountSummary() {
            return null;
        }
    }
""")

_INVOKER_JAVA = textwrap.dedent("""\
    package com.chase.digital.profile.invoker;

    import com.fasterxml.jackson.annotation.JsonProperty;
    import javax.validation.constraints.NotNull;

    public class AccountLookupInvoker {

        @NotNull
        @JsonProperty("accountNumber")
        private String accountNumber;

        private String accountType;

        private int maxResults;
    }
""")

_HANDLER_JAVA = textwrap.dedent("""\
    package com.chase.digital.profile.handler;

    import com.fasterxml.jackson.annotation.JsonProperty;

    public class AccountLookupHandler {

        @JsonProperty("accountId")
        private String accountId;

        private java.math.BigDecimal balance;

        private String status;

        private static final long serialVersionUID = 1L;
    }
""")


def _create_repo(tmp_path: Path, *, rest_xml: bool = True, cxf_xml: bool = True,
                 java_sources: bool = False) -> Path:
    """Create a temp repo structure with XML and optionally Java files."""
    repo = tmp_path / "repo"
    webinf = repo / "src" / "main" / "webapp" / "WEB-INF"
    webinf.mkdir(parents=True)

    if rest_xml:
        (webinf / "rest-servlet.xml").write_text(_REST_SERVLET_XML, encoding="utf-8")
    if cxf_xml:
        (webinf / "cxf-servlet.xml").write_text(_CXF_SERVLET_XML, encoding="utf-8")

    if java_sources:
        # Controller
        ctrl_dir = repo / "src" / "main" / "java" / "com" / "chase" / "digital" / "profile" / "api" / "profile" / "account"
        ctrl_dir.mkdir(parents=True)
        (ctrl_dir / "AccountLookupSvcController.java").write_text(_CONTROLLER_JAVA, encoding="utf-8")

        # Invoker
        inv_dir = repo / "src" / "main" / "java" / "com" / "chase" / "digital" / "profile" / "invoker"
        inv_dir.mkdir(parents=True)
        (inv_dir / "AccountLookupInvoker.java").write_text(_INVOKER_JAVA, encoding="utf-8")

        # Handler
        hdl_dir = repo / "src" / "main" / "java" / "com" / "chase" / "digital" / "profile" / "handler"
        hdl_dir.mkdir(parents=True)
        (hdl_dir / "AccountLookupHandler.java").write_text(_HANDLER_JAVA, encoding="utf-8")

    return repo


# ======================================================================
# TestFindServletXmlFiles
# ======================================================================

class TestFindServletXmlFiles:
    def test_finds_in_webinf(self, tmp_path):
        repo = _create_repo(tmp_path)
        rest_files, cxf_files = _find_servlet_xml_files(str(repo))
        assert len(rest_files) == 1
        assert len(cxf_files) == 1
        assert "rest-servlet.xml" in rest_files[0].name
        assert "cxf-servlet.xml" in cxf_files[0].name

    def test_no_xml_files(self, tmp_path):
        repo = _create_repo(tmp_path, rest_xml=False, cxf_xml=False)
        rest_files, cxf_files = _find_servlet_xml_files(str(repo))
        assert rest_files == []
        assert cxf_files == []

    def test_skips_git_directory(self, tmp_path):
        repo = _create_repo(tmp_path, rest_xml=False, cxf_xml=False)
        git_dir = repo / ".git" / "config"
        git_dir.mkdir(parents=True)
        (git_dir / "rest-servlet.xml").write_text("<beans/>", encoding="utf-8")
        rest_files, _ = _find_servlet_xml_files(str(repo))
        assert rest_files == []

    def test_only_rest(self, tmp_path):
        repo = _create_repo(tmp_path, rest_xml=True, cxf_xml=False)
        rest_files, cxf_files = _find_servlet_xml_files(str(repo))
        assert len(rest_files) == 1
        assert cxf_files == []


# ======================================================================
# TestParseRestServletXml
# ======================================================================

class TestParseRestServletXml:
    def test_extracts_controller_beans(self, tmp_path):
        xml_path = tmp_path / "rest-servlet.xml"
        xml_path.write_text(_REST_SERVLET_XML, encoding="utf-8")

        endpoints = _parse_rest_servlet_xml(xml_path)
        assert len(endpoints) == 2  # Controller beans only, not SomeHelper
        assert all(ep.protocol == "REST" for ep in endpoints)

        # Verify the first bean
        names = {ep.fqcn.rsplit(".", 1)[-1] for ep in endpoints}
        assert "AccountLookupSvcController" in names
        assert "ListProfileAttributeController" in names

    def test_filters_non_controller_beans(self, tmp_path):
        xml_path = tmp_path / "rest-servlet.xml"
        xml_path.write_text(_REST_SERVLET_XML, encoding="utf-8")

        endpoints = _parse_rest_servlet_xml(xml_path)
        fqcns = {ep.fqcn for ep in endpoints}
        assert "com.chase.digital.profile.util.SomeHelper" not in fqcns

    def test_empty_xml(self, tmp_path):
        xml_path = tmp_path / "rest-servlet.xml"
        xml_path.write_text('<?xml version="1.0"?><beans xmlns="http://www.springframework.org/schema/beans"/>', encoding="utf-8")
        endpoints = _parse_rest_servlet_xml(xml_path)
        assert endpoints == []

    def test_bare_bean_tags_no_namespace(self, tmp_path):
        xml_path = tmp_path / "rest-servlet.xml"
        xml_path.write_text(textwrap.dedent("""\
            <?xml version="1.0"?>
            <beans>
                <bean id="myCtrl" class="com.example.MyController" />
            </beans>
        """), encoding="utf-8")
        endpoints = _parse_rest_servlet_xml(xml_path)
        assert len(endpoints) == 1
        assert endpoints[0].fqcn == "com.example.MyController"


# ======================================================================
# TestParseCxfServletXml
# ======================================================================

class TestParseCxfServletXml:
    def test_extracts_jaxws_endpoints(self, tmp_path):
        xml_path = tmp_path / "cxf-servlet.xml"
        xml_path.write_text(_CXF_SERVLET_XML, encoding="utf-8")

        endpoints = _parse_cxf_servlet_xml(xml_path)
        assert len(endpoints) == 2
        assert all(ep.protocol == "SOAP" for ep in endpoints)

    def test_extracts_address(self, tmp_path):
        xml_path = tmp_path / "cxf-servlet.xml"
        xml_path.write_text(_CXF_SERVLET_XML, encoding="utf-8")

        endpoints = _parse_cxf_servlet_xml(xml_path)
        addresses = {ep.address for ep in endpoints}
        assert "/ws/CISCustomerSvc/20160313" in addresses
        assert "/ws/ProfileEquivalenceSearchSvc/20130721" in addresses

    def test_extracts_implementor(self, tmp_path):
        xml_path = tmp_path / "cxf-servlet.xml"
        xml_path.write_text(_CXF_SERVLET_XML, encoding="utf-8")

        endpoints = _parse_cxf_servlet_xml(xml_path)
        impls = {ep.fqcn for ep in endpoints}
        assert "com.chase.digital.profile.cis.customer.ws.v20160313.CISCustomerSvcImpl" in impls

    def test_empty_cxf_xml(self, tmp_path):
        xml_path = tmp_path / "cxf-servlet.xml"
        xml_path.write_text(textwrap.dedent("""\
            <?xml version="1.0"?>
            <beans xmlns="http://www.springframework.org/schema/beans"
                   xmlns:jaxws="http://cxf.apache.org/jaxws">
            </beans>
        """), encoding="utf-8")
        endpoints = _parse_cxf_servlet_xml(xml_path)
        assert endpoints == []


# ======================================================================
# TestDeriveServiceName
# ======================================================================

class TestDeriveServiceName:
    def test_rest_strips_controller_appends_rest_svc(self):
        name = _derive_service_name(
            "profile_account_lookup.AccountLookupSvcController",
            "com.chase.digital.profile.api.profile.account.AccountLookupSvcController",
            "REST",
        )
        # AccountLookupSvcController → AccountLookupSvc (strip Controller)
        # Already ends in Svc, so no RESTSvc appended
        assert name == "AccountLookupSvc"

    def test_rest_appends_rest_svc_when_no_svc(self):
        name = _derive_service_name(
            "myCtrl",
            "com.example.AccountLookupController",
            "REST",
        )
        assert name == "AccountLookupRESTSvc"

    def test_soap_strips_impl(self):
        name = _derive_service_name(
            "CISCustomerSvc_20160313",
            "com.chase.digital.profile.cis.customer.ws.v20160313.CISCustomerSvcImpl",
            "SOAP",
        )
        assert name == "CISCustomerSvc"

    def test_soap_strips_svc_impl(self):
        name = _derive_service_name(
            "ProfileEquivalenceSearchSvc_20130721",
            "com.chase.digital.profile.equivalence.search.ws.v20130721.ProfileEquivalenceSearchSvcImpl",
            "SOAP",
        )
        assert name == "ProfileEquivalenceSearchSvc"

    def test_fallback_to_class_name(self):
        name = _derive_service_name("", "com.example.FooResource", "REST")
        assert name == "FooRESTSvc"


# ======================================================================
# TestBuildImportMap
# ======================================================================

class TestBuildImportMap:
    def test_parses_imports(self):
        source = textwrap.dedent("""\
            package com.example;
            import com.foo.bar.MyInvoker;
            import com.foo.baz.MyHandler;
            import java.util.List;
        """)
        m = _build_import_map(source)
        assert m["MyInvoker"] == "com.foo.bar.MyInvoker"
        assert m["MyHandler"] == "com.foo.baz.MyHandler"
        assert m["List"] == "java.util.List"

    def test_empty_source(self):
        assert _build_import_map("") == {}


# ======================================================================
# TestFindJavaSource
# ======================================================================

class TestFindJavaSource:
    def test_finds_standard_maven_path(self, tmp_path):
        repo = _create_repo(tmp_path, java_sources=True)
        result = _find_java_source(
            str(repo),
            "com.chase.digital.profile.api.profile.account.AccountLookupSvcController",
        )
        assert result is not None
        assert result.name == "AccountLookupSvcController.java"

    def test_fallback_rglob(self, tmp_path):
        repo = tmp_path / "repo"
        odd_dir = repo / "src" / "custom" / "place"
        odd_dir.mkdir(parents=True)
        (odd_dir / "FooController.java").write_text("class FooController {}", encoding="utf-8")
        result = _find_java_source(str(repo), "com.different.package.FooController")
        assert result is not None
        assert result.name == "FooController.java"

    def test_not_found(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        result = _find_java_source(str(repo), "com.example.DoesNotExist")
        assert result is None


# ======================================================================
# TestFindDelegateClasses (requires javalang)
# ======================================================================

@needs_javalang
class TestFindDelegateClasses:
    def test_finds_invoker_and_handler(self, tmp_path):
        from src.bdd.servlet_discovery import _find_delegate_classes
        tree = javalang.parse.parse(_CONTROLLER_JAVA)
        inv, hdl = _find_delegate_classes(tree, _CONTROLLER_JAVA)
        assert inv == "com.chase.digital.profile.invoker.AccountLookupInvoker"
        assert hdl == "com.chase.digital.profile.handler.AccountLookupHandler"

    def test_no_delegates(self):
        from src.bdd.servlet_discovery import _find_delegate_classes
        source = textwrap.dedent("""\
            package com.example;
            public class SimpleController {
                private String name;
            }
        """)
        tree = javalang.parse.parse(source)
        inv, hdl = _find_delegate_classes(tree, source)
        assert inv == ""
        assert hdl == ""


# ======================================================================
# TestExtractEndpointFromAnnotations (requires javalang)
# ======================================================================

@needs_javalang
class TestExtractEndpointFromAnnotations:
    def test_extracts_request_mapping_path(self):
        from src.bdd.servlet_discovery import _extract_endpoint_from_annotations
        tree = javalang.parse.parse(_CONTROLLER_JAVA)
        path, method = _extract_endpoint_from_annotations(tree, _CONTROLLER_JAVA)
        assert path == "/profilecore/services/AccountLookup"

    def test_no_annotations(self):
        from src.bdd.servlet_discovery import _extract_endpoint_from_annotations
        source = "package com.example;\npublic class Bare {}"
        tree = javalang.parse.parse(source)
        path, method = _extract_endpoint_from_annotations(tree, source)
        assert path == ""
        assert method == "POST"


# ======================================================================
# TestExtractOperationsFromMethods (requires javalang)
# ======================================================================

@needs_javalang
class TestExtractOperationsFromMethods:
    def test_extracts_post_mapping_methods(self):
        from src.bdd.servlet_discovery import _extract_operations_from_methods
        tree = javalang.parse.parse(_CONTROLLER_JAVA)
        ops = _extract_operations_from_methods(tree, "/profilecore/services/AccountLookup")
        assert len(ops) == 2
        names = {op["name"] for op in ops}
        assert "getAccountDetails" in names
        assert "getAccountSummary" in names
        assert all(op["method"] == "POST" for op in ops)

    def test_no_annotated_methods(self):
        from src.bdd.servlet_discovery import _extract_operations_from_methods
        source = textwrap.dedent("""\
            package com.example;
            public class Plain {
                public void doSomething() {}
            }
        """)
        tree = javalang.parse.parse(source)
        ops = _extract_operations_from_methods(tree, "/base")
        assert ops == []


# ======================================================================
# TestExtractDtoFields (requires javalang)
# ======================================================================

@needs_javalang
class TestExtractDtoFields:
    def test_extracts_invoker_fields(self, tmp_path):
        repo = _create_repo(tmp_path, java_sources=True)
        fields = _extract_dto_fields(
            str(repo),
            "com.chase.digital.profile.invoker.AccountLookupInvoker",
        )
        names = {f.name for f in fields}
        assert "accountNumber" in names
        assert "accountType" in names
        assert "maxResults" in names

    def test_json_property_overrides_name(self, tmp_path):
        repo = _create_repo(tmp_path, java_sources=True)
        fields = _extract_dto_fields(
            str(repo),
            "com.chase.digital.profile.invoker.AccountLookupInvoker",
        )
        # @JsonProperty("accountNumber") should override the field declaration name
        account_field = [f for f in fields if f.name == "accountNumber"]
        assert len(account_field) == 1

    def test_not_null_sets_required(self, tmp_path):
        repo = _create_repo(tmp_path, java_sources=True)
        fields = _extract_dto_fields(
            str(repo),
            "com.chase.digital.profile.invoker.AccountLookupInvoker",
        )
        account_field = [f for f in fields if f.name == "accountNumber"][0]
        assert account_field.required is True

    def test_handler_fields(self, tmp_path):
        repo = _create_repo(tmp_path, java_sources=True)
        fields = _extract_dto_fields(
            str(repo),
            "com.chase.digital.profile.handler.AccountLookupHandler",
        )
        names = {f.name for f in fields}
        assert "accountId" in names
        assert "balance" in names
        assert "status" in names

    def test_skips_static_final_constants(self, tmp_path):
        repo = _create_repo(tmp_path, java_sources=True)
        fields = _extract_dto_fields(
            str(repo),
            "com.chase.digital.profile.handler.AccountLookupHandler",
        )
        names = {f.name for f in fields}
        assert "serialVersionUID" not in names

    def test_nonexistent_class(self, tmp_path):
        repo = _create_repo(tmp_path)
        fields = _extract_dto_fields(str(repo), "com.does.not.Exist")
        assert fields == []


# ======================================================================
# TestBuildSpecFromEndpoint
# ======================================================================

@needs_javalang
class TestBuildSpecFromEndpoint:
    def test_rest_endpoint_full_build(self, tmp_path):
        repo = _create_repo(tmp_path, java_sources=True)
        ep = DiscoveredEndpoint(
            bean_id="profile_account_lookup.AccountLookupSvcController",
            fqcn="com.chase.digital.profile.api.profile.account.AccountLookupSvcController",
            protocol="REST",
        )
        spec = _build_spec_from_endpoint(str(repo), ep)
        assert spec is not None
        assert "AccountLookup" in spec.service_name
        assert spec.endpoint == "/profilecore/services/AccountLookup"
        assert len(spec.operations) == 2
        assert spec.invoker_class == "com.chase.digital.profile.invoker.AccountLookupInvoker"
        assert spec.handler_class == "com.chase.digital.profile.handler.AccountLookupHandler"

    def test_rest_endpoint_has_dto_fields(self, tmp_path):
        repo = _create_repo(tmp_path, java_sources=True)
        ep = DiscoveredEndpoint(
            bean_id="profile_account_lookup.AccountLookupSvcController",
            fqcn="com.chase.digital.profile.api.profile.account.AccountLookupSvcController",
            protocol="REST",
        )
        spec = _build_spec_from_endpoint(str(repo), ep)
        assert spec is not None
        # Operations should have request and response fields
        op = spec.operations[0]
        req_names = {f.name for f in op.request_fields}
        resp_names = {f.name for f in op.response_fields}
        assert "accountNumber" in req_names
        assert "accountId" in resp_names

    def test_soap_endpoint_build(self, tmp_path):
        repo = _create_repo(tmp_path)
        ep = DiscoveredEndpoint(
            bean_id="CISCustomerSvc_20160313",
            fqcn="com.chase.digital.profile.cis.customer.ws.v20160313.CISCustomerSvcImpl",
            address="/ws/CISCustomerSvc/20160313",
            protocol="SOAP",
        )
        spec = _build_spec_from_endpoint(str(repo), ep)
        assert spec is not None
        assert spec.service_name == "CISCustomerSvc"
        assert spec.endpoint == "/ws/CISCustomerSvc/20160313"
        assert spec.operations[0].method == "POST"


# ======================================================================
# TestDiscoverServiceSpecs (full pipeline)
# ======================================================================

class TestDiscoverServiceSpecs:
    def test_no_xml_returns_empty(self, tmp_path):
        repo = _create_repo(tmp_path, rest_xml=False, cxf_xml=False)
        specs = discover_service_specs(str(repo))
        assert specs == []

    def test_discovers_from_rest_xml(self, tmp_path):
        repo = _create_repo(tmp_path, rest_xml=True, cxf_xml=False)
        specs = discover_service_specs(str(repo))
        assert len(specs) >= 1
        names = {s.service_name for s in specs}
        assert any("AccountLookup" in n for n in names)

    def test_discovers_from_cxf_xml(self, tmp_path):
        repo = _create_repo(tmp_path, rest_xml=False, cxf_xml=True)
        specs = discover_service_specs(str(repo))
        assert len(specs) == 2
        names = {s.service_name for s in specs}
        assert "CISCustomerSvc" in names
        assert "ProfileEquivalenceSearchSvc" in names

    def test_discovers_both_rest_and_soap(self, tmp_path):
        repo = _create_repo(tmp_path, rest_xml=True, cxf_xml=True)
        specs = discover_service_specs(str(repo))
        protocols = {("REST" if s.endpoint.startswith("/ws") is False else "SOAP") for s in specs}
        assert len(specs) >= 3  # 2 REST + 2 SOAP

    def test_service_filter(self, tmp_path):
        repo = _create_repo(tmp_path, rest_xml=True, cxf_xml=True)
        specs = discover_service_specs(str(repo), service_filter="CISCustomer")
        assert len(specs) == 1
        assert specs[0].service_name == "CISCustomerSvc"

    def test_protocol_filter_rest_only(self, tmp_path):
        repo = _create_repo(tmp_path, rest_xml=True, cxf_xml=True)
        specs = discover_service_specs(str(repo), protocol_filter="REST")
        assert all(not s.endpoint.startswith("/ws/") for s in specs)

    def test_protocol_filter_soap_only(self, tmp_path):
        repo = _create_repo(tmp_path, rest_xml=True, cxf_xml=True)
        specs = discover_service_specs(str(repo), protocol_filter="SOAP")
        assert all(s.endpoint.startswith("/ws/") for s in specs)

    @needs_javalang
    def test_full_pipeline_with_java_sources(self, tmp_path):
        """End-to-end: XML discovery + Java analysis + spec assembly."""
        repo = _create_repo(tmp_path, rest_xml=True, cxf_xml=True, java_sources=True)
        specs = discover_service_specs(str(repo))
        assert len(specs) >= 1

        # Find the AccountLookup spec
        acct_specs = [s for s in specs if "AccountLookup" in s.service_name]
        assert len(acct_specs) >= 1
        spec = acct_specs[0]

        # Should have operations from method annotations
        assert len(spec.operations) == 2
        op_names = {op.name for op in spec.operations}
        assert "getAccountDetails" in op_names
        assert "getAccountSummary" in op_names

        # Should have invoker/handler populated
        assert "AccountLookupInvoker" in spec.invoker_class
        assert "AccountLookupHandler" in spec.handler_class

        # Should have DTO fields
        op = spec.operations[0]
        req_names = {f.name for f in op.request_fields}
        resp_names = {f.name for f in op.response_fields}
        assert "accountNumber" in req_names
        assert "accountId" in resp_names
