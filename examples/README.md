# Examples

## changes/

Example requirement files for different testing strategies and project types:

| File | Use case |
|------|----------|
| `changes_bdd.txt` | BDD / Cucumber tests |
| `changes_contract.txt` | Contract testing (Pact, Spring Cloud Contract) |
| `changes_integration.txt` | Integration tests (TestContainers, REST Assured) |
| `changes_java.txt` | Java unit tests (StringUtils, etc.) |
| `changes_soap.txt` | SOAP / legacy web service tests |
| `changes_springboot.txt` | Spring Boot features |

Usage: `python main.py --changes examples/changes/changes_bdd.txt`
