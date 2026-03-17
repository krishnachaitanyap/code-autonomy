'use client';

import { useState } from 'react';
import type { WorkflowSubtask } from '@/lib/api';
import WorkflowDiagram from '@/components/WorkflowDiagram';

// ---------------------------------------------------------------------------
// Sample workflows to demo different states
// ---------------------------------------------------------------------------

const SAMPLE_COMPLETED: WorkflowSubtask[] = [
  {
    index: 0, title: 'Discover REST endpoints', description: 'Scan source code for @RestController, @RequestMapping annotations and OpenAPI specs to build endpoint inventory.',
    type: 'discovery', status: 'completed', checkpoint: false, requirements: '',
    result_summary: 'Found 14 REST endpoints across 3 controllers: UserController (5), OrderController (6), PaymentController (3)',
    files_changed: [], error: null, started_at: '2026-03-17T10:00:00Z', completed_at: '2026-03-17T10:00:45Z',
    attempts: 1, model_used: 'gpt-4o', tokens_used: 12400,
  },
  {
    index: 1, title: 'Generate security BDD tests', description: 'Create Cucumber BDD feature files with OWASP Top 10 security scenarios for each discovered endpoint.',
    type: 'agent', status: 'completed', checkpoint: true, requirements: '',
    result_summary: 'Generated 42 security test scenarios across 6 feature files covering SQL injection, XSS, CSRF, auth bypass, and rate limiting.',
    files_changed: ['src/test/resources/features/security-user.feature', 'src/test/resources/features/security-order.feature', 'src/test/resources/features/security-payment.feature', 'src/test/java/steps/SecuritySteps.java', 'src/test/java/steps/AuthSteps.java', 'src/test/java/config/SecurityTestConfig.java'],
    error: null, started_at: '2026-03-17T10:01:00Z', completed_at: '2026-03-17T10:04:30Z',
    attempts: 1, model_used: 'gpt-4o', tokens_used: 89000,
  },
  {
    index: 2, title: 'Execute security tests', description: 'Run mvn test -Dtest=SecurityTest to execute the generated BDD test suite.',
    type: 'test', status: 'completed', checkpoint: false, requirements: '',
    result_summary: '38/42 tests passed. 4 tests skipped (require external auth service).',
    files_changed: [], error: null, started_at: '2026-03-17T10:05:00Z', completed_at: '2026-03-17T10:06:15Z',
    attempts: 1, model_used: '', tokens_used: 0,
  },
  {
    index: 3, title: 'Analyze test coverage', description: 'Generate JaCoCo coverage report and identify uncovered security-critical code paths.',
    type: 'coverage', status: 'completed', checkpoint: false, requirements: '',
    result_summary: 'Overall coverage: 78%. Security-critical paths: 92% covered. Gaps: PaymentController.refund() auth check, OrderController.bulkDelete() input validation.',
    files_changed: [], error: null, started_at: '2026-03-17T10:06:30Z', completed_at: '2026-03-17T10:07:00Z',
    attempts: 1, model_used: 'gpt-4o', tokens_used: 8200,
  },
];

const SAMPLE_RUNNING: WorkflowSubtask[] = [
  {
    index: 0, title: 'Discover service architecture', description: 'Map microservice boundaries, API contracts, and inter-service communication patterns.',
    type: 'discovery', status: 'completed', checkpoint: false, requirements: '',
    result_summary: 'Identified 3 services: auth-service, order-service, notification-service. Communication via REST + Kafka.',
    files_changed: [], error: null, started_at: '2026-03-17T14:00:00Z', completed_at: '2026-03-17T14:01:20Z',
    attempts: 1, model_used: 'gpt-4o', tokens_used: 15000,
  },
  {
    index: 1, title: 'Implement retry middleware', description: 'Add resilience4j retry + circuit breaker patterns to all inter-service REST calls with exponential backoff.',
    type: 'agent', status: 'completed', checkpoint: false, requirements: '',
    result_summary: 'Added RetryConfig, CircuitBreakerConfig, and @Retry annotations to OrderServiceClient and NotificationServiceClient.',
    files_changed: ['src/main/java/config/ResilienceConfig.java', 'src/main/java/client/OrderServiceClient.java', 'src/main/java/client/NotificationServiceClient.java', 'pom.xml'],
    error: null, started_at: '2026-03-17T14:01:30Z', completed_at: '2026-03-17T14:05:00Z',
    attempts: 2, model_used: 'gpt-4o', tokens_used: 67000,
  },
  {
    index: 2, title: 'Add Kafka dead-letter queue', description: 'Configure DLQ for failed Kafka messages with retry topic and error logging.',
    type: 'agent', status: 'running', checkpoint: true, requirements: '',
    result_summary: '', files_changed: ['src/main/java/config/KafkaConfig.java'],
    error: null, started_at: '2026-03-17T14:05:15Z', completed_at: null,
    attempts: 1, model_used: 'gpt-4o', tokens_used: 32000,
  },
  {
    index: 3, title: 'Generate integration tests', description: 'Create Testcontainers-based integration tests for retry and DLQ behavior.',
    type: 'agent', status: 'pending', checkpoint: false, requirements: '',
    result_summary: '', files_changed: [], error: null, started_at: null, completed_at: null,
    attempts: 1, model_used: '', tokens_used: 0,
  },
  {
    index: 4, title: 'Run integration test suite', description: 'Execute integration tests with embedded Kafka and verify resilience patterns.',
    type: 'command', status: 'pending', checkpoint: false, requirements: '',
    result_summary: '', files_changed: [], error: null, started_at: null, completed_at: null,
    attempts: 1, model_used: '', tokens_used: 0,
  },
];

const SAMPLE_FAILED: WorkflowSubtask[] = [
  {
    index: 0, title: 'Analyze database schema', description: 'Inspect current PostgreSQL schema and identify tables, relationships, and constraints.',
    type: 'discovery', status: 'completed', checkpoint: false, requirements: '',
    result_summary: 'Found 12 tables with 8 foreign key relationships. Main entities: User, Order, Product, Payment.',
    files_changed: [], error: null, started_at: '2026-03-17T09:00:00Z', completed_at: '2026-03-17T09:00:30Z',
    attempts: 1, model_used: 'gpt-4o', tokens_used: 11000,
  },
  {
    index: 1, title: 'Generate Flyway migrations', description: 'Create Flyway SQL migration scripts to add audit columns (created_at, updated_at, created_by) to all tables.',
    type: 'agent', status: 'completed', checkpoint: true, requirements: '',
    result_summary: 'Generated 4 migration scripts: V5__add_audit_columns.sql, V6__add_audit_triggers.sql, V7__backfill_audit_data.sql, V8__add_audit_indexes.sql',
    files_changed: ['src/main/resources/db/migration/V5__add_audit_columns.sql', 'src/main/resources/db/migration/V6__add_audit_triggers.sql', 'src/main/resources/db/migration/V7__backfill_audit_data.sql', 'src/main/resources/db/migration/V8__add_audit_indexes.sql'],
    error: null, started_at: '2026-03-17T09:01:00Z', completed_at: '2026-03-17T09:03:00Z',
    attempts: 1, model_used: 'gpt-4o', tokens_used: 45000,
  },
  {
    index: 2, title: 'Update JPA entities', description: 'Add @CreatedDate, @LastModifiedDate, @CreatedBy annotations to all entity classes using Spring Data JPA auditing.',
    type: 'agent', status: 'failed', checkpoint: false, requirements: '',
    result_summary: '', files_changed: ['src/main/java/entity/User.java', 'src/main/java/entity/Order.java'],
    error: 'Compilation error: AuditingEntityListener not found. Missing spring-data-jpa dependency in pom.xml. Attempted to add dependency but version conflict with existing spring-boot-starter-data-jpa 2.7.x.',
    started_at: '2026-03-17T09:03:15Z', completed_at: '2026-03-17T09:06:45Z',
    attempts: 3, model_used: 'gpt-4o', tokens_used: 92000,
  },
  {
    index: 3, title: 'Run migration tests', description: 'Execute Flyway migrations against Testcontainers PostgreSQL and verify schema changes.',
    type: 'test', status: 'skipped', checkpoint: false, requirements: '',
    result_summary: '', files_changed: [], error: 'Skipped due to previous step failure.',
    started_at: null, completed_at: null, attempts: 1, model_used: '', tokens_used: 0,
  },
];

const SAMPLE_PAUSED: WorkflowSubtask[] = [
  {
    index: 0, title: 'Discover API endpoints', description: 'Scan controllers for REST endpoints and build API inventory.',
    type: 'discovery', status: 'completed', checkpoint: false, requirements: '',
    result_summary: 'Found 8 endpoints in UserController and OrderController.',
    files_changed: [], error: null, started_at: '2026-03-17T16:00:00Z', completed_at: '2026-03-17T16:00:40Z',
    attempts: 1, model_used: 'gpt-4o', tokens_used: 9500,
  },
  {
    index: 1, title: 'Generate OpenAPI spec', description: 'Create OpenAPI 3.0 specification from discovered endpoints with request/response schemas.',
    type: 'agent', status: 'completed', checkpoint: true, requirements: '',
    result_summary: 'Generated openapi.yaml with 8 paths, 12 schemas, and example requests.',
    files_changed: ['src/main/resources/openapi.yaml', 'src/main/java/config/SwaggerConfig.java'],
    error: null, started_at: '2026-03-17T16:01:00Z', completed_at: '2026-03-17T16:03:30Z',
    attempts: 1, model_used: 'gpt-4o', tokens_used: 52000,
  },
  {
    index: 2, title: 'Generate contract tests', description: 'Create Spring Cloud Contract tests from OpenAPI spec for consumer-driven testing.',
    type: 'agent', status: 'pending', checkpoint: false, requirements: '',
    result_summary: '', files_changed: [], error: null, started_at: null, completed_at: null,
    attempts: 1, model_used: '', tokens_used: 0,
  },
];

// ---------------------------------------------------------------------------
// Demo page
// ---------------------------------------------------------------------------

type DemoScenario = 'completed' | 'running' | 'failed' | 'paused';

type RecipeInfo = { id: string; name: string; category: string; description: string; tool_names: string[] };

const SAMPLE_RECIPES: RecipeInfo[] = [
  { id: 'nucleus_full', name: 'Nucleus Full Migration', category: 'java', description: 'Complete Nucleus-to-Photon migration with framework detection and config validation.', tool_names: ['Enterprise Framework Detector', 'Config Migration Validator', 'Dependency Compatibility Checker'] },
  { id: 'spring_boot_upgrade', name: 'Spring Boot Version Upgrade (2.x->3.x)', category: 'java', description: 'Upgrade Spring Boot version with namespace migration and auto-configuration updates.', tool_names: [] },
];

const SCENARIOS: Record<DemoScenario, { label: string; subtasks: WorkflowSubtask[]; goal: string; status: string; mode: string; currentStep: number; recipes?: RecipeInfo[] }> = {
  completed: {
    label: 'Completed',
    subtasks: SAMPLE_COMPLETED,
    goal: 'Add comprehensive security BDD tests for all REST endpoints with OWASP Top 10 coverage',
    status: 'completed',
    mode: 'testing',
    currentStep: 3,
  },
  running: {
    label: 'Running (with Recipes)',
    subtasks: SAMPLE_RUNNING,
    goal: 'Implement resilience patterns (retry, circuit breaker, DLQ) across all microservice communication',
    status: 'running',
    mode: 'engineering',
    currentStep: 2,
    recipes: SAMPLE_RECIPES,
  },
  failed: {
    label: 'Failed',
    subtasks: SAMPLE_FAILED,
    goal: 'Add audit trail columns and JPA auditing to all database entities',
    status: 'failed',
    mode: 'engineering',
    currentStep: 2,
    recipes: [SAMPLE_RECIPES[1]],
  },
  paused: {
    label: 'Paused (Checkpoint)',
    subtasks: SAMPLE_PAUSED,
    goal: 'Generate OpenAPI spec and contract tests from existing REST controllers',
    status: 'paused',
    mode: 'testing',
    currentStep: 2,
  },
};

export default function WorkflowDemoPage() {
  const [activeScenario, setActiveScenario] = useState<DemoScenario>('running');
  const scenario = SCENARIOS[activeScenario];

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-6xl mx-auto space-y-6">
        {/* Page header */}
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Workflow Diagram Demo</h1>
          <p className="text-sm text-gray-500 mt-1">Visual workflow execution diagrams — click nodes to see details</p>
        </div>

        {/* Scenario selector */}
        <div className="bg-white border border-gray-200 rounded-xl p-4">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Select Scenario</h2>
          <div className="flex gap-2 flex-wrap">
            {(Object.keys(SCENARIOS) as DemoScenario[]).map((key) => (
              <button
                key={key}
                onClick={() => setActiveScenario(key)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  activeScenario === key
                    ? key === 'completed' ? 'bg-green-600 text-white' :
                      key === 'running' ? 'bg-blue-600 text-white' :
                      key === 'failed' ? 'bg-red-600 text-white' :
                      'bg-amber-500 text-white'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {SCENARIOS[key].label}
                <span className="ml-1.5 text-xs opacity-75">({SCENARIOS[key].subtasks.length} steps)</span>
              </button>
            ))}
          </div>
        </div>

        {/* The actual diagram */}
        <WorkflowDiagram
          subtasks={scenario.subtasks}
          currentStep={scenario.currentStep}
          goal={scenario.goal}
          status={scenario.status}
          mode={scenario.mode}
          recipes={scenario.recipes}
        />
      </div>
    </div>
  );
}
