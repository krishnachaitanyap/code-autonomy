'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { repos, migrations, type Repo, type DatabaseConnectionConfig } from '@/lib/api';

type WizardStep = 1 | 2 | 3 | 4;

const SQL_ENGINES = [
  { value: 'postgresql', label: 'PostgreSQL', defaultPort: '5432', type: 'sql' as const },
  { value: 'mysql', label: 'MySQL', defaultPort: '3306', type: 'sql' as const },
  { value: 'oracle', label: 'Oracle', defaultPort: '1521', type: 'sql' as const },
  { value: 'sqlserver', label: 'SQL Server', defaultPort: '1433', type: 'sql' as const },
];

const NOSQL_ENGINES = [
  { value: 'mongodb', label: 'MongoDB', defaultPort: '27017', type: 'nosql' as const },
  { value: 'cassandra', label: 'Cassandra', defaultPort: '9042', type: 'nosql' as const },
  { value: 'redis', label: 'Redis', defaultPort: '6379', type: 'nosql' as const },
  { value: 'elasticsearch', label: 'Elasticsearch', defaultPort: '9200', type: 'nosql' as const },
  { value: 'dynamodb', label: 'DynamoDB', defaultPort: '8000', type: 'nosql' as const },
  { value: 'couchbase', label: 'Couchbase', defaultPort: '8091', type: 'nosql' as const },
  { value: 'neo4j', label: 'Neo4j', defaultPort: '7687', type: 'nosql' as const },
];

const DB_ENGINES = [...SQL_ENGINES, ...NOSQL_ENGINES];

const NOSQL_ENGINE_VALUES = new Set(NOSQL_ENGINES.map(e => e.value));

function DatabaseConnectionForm({
  prefix,
  values,
  onChange,
}: {
  prefix: string;
  values: { engine: string; host: string; port: string; database: string; schema: string; jdbc_url: string; username: string };
  onChange: (field: string, value: string) => void;
}) {
  const isNoSQL = NOSQL_ENGINE_VALUES.has(values.engine);
  const isDynamoDB = values.engine === 'dynamodb';

  return (
    <div className="space-y-3">
      {/* Engine category tabs */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">Database Engine</label>
        <div className="mb-2">
          <span className="text-[10px] font-medium text-gray-400 uppercase tracking-wider">SQL</span>
          <div className="flex flex-wrap gap-1.5 mt-1">
            {SQL_ENGINES.map(eng => (
              <button
                key={eng.value}
                type="button"
                onClick={() => {
                  onChange('engine', eng.value);
                  if (!values.port || DB_ENGINES.some(e => e.defaultPort === values.port)) {
                    onChange('port', eng.defaultPort);
                  }
                }}
                className={`px-3 py-1.5 rounded-md text-xs border transition-colors ${
                  values.engine === eng.value
                    ? 'border-cyan-500 bg-cyan-50 text-cyan-700 font-medium'
                    : 'border-gray-200 text-gray-600 hover:bg-gray-50'
                }`}
              >
                {eng.label}
              </button>
            ))}
          </div>
        </div>
        <div>
          <span className="text-[10px] font-medium text-gray-400 uppercase tracking-wider">NoSQL</span>
          <div className="flex flex-wrap gap-1.5 mt-1">
            {NOSQL_ENGINES.map(eng => (
              <button
                key={eng.value}
                type="button"
                onClick={() => {
                  onChange('engine', eng.value);
                  if (!values.port || DB_ENGINES.some(e => e.defaultPort === values.port)) {
                    onChange('port', eng.defaultPort);
                  }
                }}
                className={`px-3 py-1.5 rounded-md text-xs border transition-colors ${
                  values.engine === eng.value
                    ? 'border-violet-500 bg-violet-50 text-violet-700 font-medium'
                    : 'border-gray-200 text-gray-600 hover:bg-gray-50'
                }`}
              >
                {eng.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* DynamoDB uses AWS region, not host/port */}
      {isDynamoDB ? (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Host <span className="text-gray-400 font-normal">(or &quot;aws&quot; for cloud)</span>
            </label>
            <input
              type="text"
              value={values.host}
              onChange={e => onChange('host', e.target.value)}
              placeholder="aws"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Region <span className="text-gray-400 font-normal">(as schema)</span>
            </label>
            <input
              type="text"
              value={values.schema}
              onChange={e => onChange('schema', e.target.value)}
              placeholder="us-east-1"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500"
            />
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Host</label>
            <input
              type="text"
              value={values.host}
              onChange={e => onChange('host', e.target.value)}
              placeholder="localhost"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Port</label>
            <input
              type="text"
              value={values.port}
              onChange={e => onChange('port', e.target.value)}
              placeholder={DB_ENGINES.find(e => e.value === values.engine)?.defaultPort || '5432'}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500"
            />
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            {isNoSQL && values.engine === 'redis' ? 'DB Number' : 'Database'}
          </label>
          <input
            type="text"
            value={values.database}
            onChange={e => onChange('database', e.target.value)}
            placeholder={isNoSQL && values.engine === 'redis' ? '0' : isNoSQL ? 'mydb' : 'mydb'}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500"
          />
        </div>
        {!isNoSQL && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Schema <span className="text-gray-400 font-normal">(optional)</span>
            </label>
            <input
              type="text"
              value={values.schema}
              onChange={e => onChange('schema', e.target.value)}
              placeholder="public"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500"
            />
          </div>
        )}
        {isNoSQL && values.engine === 'cassandra' && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Keyspace</label>
            <input
              type="text"
              value={values.schema}
              onChange={e => onChange('schema', e.target.value)}
              placeholder="my_keyspace"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500"
            />
          </div>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Username <span className="text-gray-400 font-normal">(optional)</span>
        </label>
        <input
          type="text"
          value={values.username}
          onChange={e => onChange('username', e.target.value)}
          placeholder={isNoSQL ? 'admin' : 'postgres'}
          className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-cyan-500"
        />
      </div>

      {/* JDBC URL alternative — only for SQL engines */}
      {!isNoSQL && (
        <>
          <div className="relative">
            <div className="absolute inset-0 flex items-center"><div className="w-full border-t border-gray-200" /></div>
            <div className="relative flex justify-center text-sm"><span className="bg-white px-2 text-gray-400">or use JDBC URL</span></div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              JDBC URL <span className="text-gray-400 font-normal">(alternative)</span>
            </label>
            <input
              type="text"
              value={values.jdbc_url}
              onChange={e => onChange('jdbc_url', e.target.value)}
              placeholder="jdbc:postgresql://localhost:5432/mydb"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono focus:outline-none focus:ring-2 focus:ring-cyan-500"
            />
          </div>
        </>
      )}

      {/* Connection string for NoSQL engines */}
      {isNoSQL && (
        <>
          <div className="relative">
            <div className="absolute inset-0 flex items-center"><div className="w-full border-t border-gray-200" /></div>
            <div className="relative flex justify-center text-sm"><span className="bg-white px-2 text-gray-400">or use connection string</span></div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Connection String <span className="text-gray-400 font-normal">(alternative)</span>
            </label>
            <input
              type="text"
              value={values.jdbc_url}
              onChange={e => onChange('jdbc_url', e.target.value)}
              placeholder={
                values.engine === 'mongodb' ? 'mongodb://localhost:27017/mydb' :
                values.engine === 'redis' ? 'redis://localhost:6379/0' :
                values.engine === 'neo4j' ? 'bolt://localhost:7687' :
                `${values.engine}://localhost`
              }
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono focus:outline-none focus:ring-2 focus:ring-cyan-500"
            />
          </div>
        </>
      )}
    </div>
  );
}

export default function NewMigrationWizard() {
  const router = useRouter();
  const [step, setStep] = useState<WizardStep>(1);
  const [existingRepos, setExistingRepos] = useState<Repo[]>([]);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);

  const [form, setForm] = useState({
    name: '',
    migration_mode: 'migration' as 'migration' | 'improvement' | 'database',
    // Source
    source_mode: 'url' as 'url' | 'path' | 'existing',
    source_repo_id: '',
    source_repo_url: '',
    source_local_path: '',
    source_branch: 'main',
    // Reference
    reference_repo_url: '',
    reference_local_path: '',
    reference_branch: 'main',
    reference_folders: [] as string[],
    // Database - source
    source_db_engine: 'postgresql',
    source_db_host: '',
    source_db_port: '5432',
    source_db_database: '',
    source_db_schema: '',
    source_db_jdbc_url: '',
    source_db_username: '',
    // Database - destination
    dest_db_engine: 'postgresql',
    dest_db_host: '',
    dest_db_port: '5432',
    dest_db_database: '',
    dest_db_schema: '',
    dest_db_jdbc_url: '',
    dest_db_username: '',
  });

  useEffect(() => {
    repos.list().then(setExistingRepos).catch(() => {});
  }, []);

  const isDatabase = form.migration_mode === 'database';
  const isImprovement = form.migration_mode === 'improvement';

  const buildDbConfig = (prefix: 'source_db' | 'dest_db'): DatabaseConnectionConfig | undefined => {
    const engine = form[`${prefix}_engine`];
    const host = form[`${prefix}_host`];
    const database = form[`${prefix}_database`];
    const jdbc_url = form[`${prefix}_jdbc_url`];
    if (!host && !jdbc_url) return undefined;
    return {
      engine,
      host,
      port: form[`${prefix}_port`],
      database,
      schema: form[`${prefix}_schema`] || undefined,
      jdbc_url: jdbc_url || undefined,
      username: form[`${prefix}_username`] || undefined,
    };
  };

  const handleCreate = async () => {
    setError('');
    setCreating(true);
    try {
      if (isDatabase) {
        const source_db = buildDbConfig('source_db');
        const destination_db = buildDbConfig('dest_db');
        const project = await migrations.createProject({
          name: form.name,
          migration_mode: 'database',
          source_db,
          destination_db,
        });
        await migrations.analyzeProject(project.id);
        router.push(`/migration/${project.id}`);
      } else {
        const sourceUrl = form.source_mode === 'existing'
          ? existingRepos.find(r => r.id === form.source_repo_id)?.url || ''
          : form.source_repo_url;
        const sourcePath = form.source_mode === 'existing'
          ? existingRepos.find(r => r.id === form.source_repo_id)?.local_path || ''
          : form.source_local_path;

        const project = await migrations.createProject({
          name: form.name,
          migration_mode: form.migration_mode,
          source_repo_url: sourceUrl,
          source_local_path: sourcePath,
          source_branch: form.source_branch,
          reference_repo_url: form.reference_repo_url,
          reference_local_path: form.reference_local_path,
          reference_branch: form.reference_branch,
          reference_folders: form.reference_folders,
        });
        await migrations.analyzeProject(project.id);
        router.push(`/migration/${project.id}`);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to create project');
      setCreating(false);
    }
  };

  const totalSteps = isDatabase ? 4 : 3;
  const isLastStep = step === totalSteps;

  const stepLabels = isDatabase
    ? { 1: 'Mode & Name', 2: 'Source Database', 3: 'Destination (Optional)', 4: 'Review' }
    : { 1: 'Repository', 2: isImprovement ? 'Reference (Optional)' : 'Reference', 3: 'Review', 4: '' };

  const canNext = () => {
    if (step === 1) {
      if (!form.name) return false;
      if (!isDatabase) {
        if (form.source_mode === 'url' && !form.source_repo_url) return false;
        if (form.source_mode === 'path' && !form.source_local_path) return false;
        if (form.source_mode === 'existing' && !form.source_repo_id) return false;
      }
      return true;
    }
    if (step === 2) {
      if (isDatabase) {
        return !!(form.source_db_host || form.source_db_jdbc_url);
      }
      return isImprovement || !!(form.reference_repo_url || form.reference_local_path);
    }
    return true;
  };

  const handleDbFieldChange = (prefix: string, field: string, value: string) => {
    setForm(prev => ({ ...prev, [`${prefix}_${field}`]: value }));
  };

  const descriptionText = isDatabase
    ? 'Compare source and destination database schemas, generate migration scripts.'
    : isImprovement
      ? 'Analyze your repository for quality, testing, performance, and structural improvements.'
      : 'Compare your source repository against a golden reference template.';

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <h1 className="text-xl font-bold text-gray-900 mb-1">New Migration Project</h1>
      <p className="text-sm text-gray-500 mb-6">{descriptionText}</p>

      {/* Step indicator */}
      <div className="flex items-center gap-2 mb-8">
        {Array.from({ length: totalSteps }, (_, i) => i + 1).map(s => (
          <div key={s} className="flex items-center gap-2">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
              step === s ? 'bg-indigo-600 text-white' :
              step > s ? 'bg-green-100 text-green-700' :
              'bg-gray-100 text-gray-500'
            }`}>
              {step > s ? '\u2713' : s}
            </div>
            <span className={`text-sm ${step === s ? 'text-gray-900 font-medium' : 'text-gray-500'}`}>
              {stepLabels[s as keyof typeof stepLabels]}
            </span>
            {s < totalSteps && <div className="w-12 h-0.5 bg-gray-200" />}
          </div>
        ))}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded text-sm mb-4">
          {error}
        </div>
      )}

      {/* Step 1: Mode + Name (+ source repo for non-database) */}
      {step === 1 && (
        <div className="space-y-4">
          {/* Mode toggle */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Mode</label>
            <div className="flex gap-2">
              <button
                onClick={() => setForm({ ...form, migration_mode: 'migration' })}
                className={`flex-1 px-3 py-2 rounded-md text-sm border transition-colors ${
                  form.migration_mode === 'migration'
                    ? 'border-indigo-500 bg-indigo-50 text-indigo-700 font-medium'
                    : 'border-gray-200 text-gray-600 hover:bg-gray-50'
                }`}
              >
                <div className="font-medium">Migration</div>
                <div className="text-[10px] mt-0.5 opacity-75">Source vs Reference comparison</div>
              </button>
              <button
                onClick={() => setForm({ ...form, migration_mode: 'improvement' })}
                className={`flex-1 px-3 py-2 rounded-md text-sm border transition-colors ${
                  form.migration_mode === 'improvement'
                    ? 'border-indigo-500 bg-indigo-50 text-indigo-700 font-medium'
                    : 'border-gray-200 text-gray-600 hover:bg-gray-50'
                }`}
              >
                <div className="font-medium">Improvement</div>
                <div className="text-[10px] mt-0.5 opacity-75">Quality, testing, performance analysis</div>
              </button>
              <button
                onClick={() => setForm({ ...form, migration_mode: 'database' })}
                className={`flex-1 px-3 py-2 rounded-md text-sm border transition-colors ${
                  form.migration_mode === 'database'
                    ? 'border-cyan-500 bg-cyan-50 text-cyan-700 font-medium'
                    : 'border-gray-200 text-gray-600 hover:bg-gray-50'
                }`}
              >
                <div className="font-medium">Database</div>
                <div className="text-[10px] mt-0.5 opacity-75">Schema comparison & DDL/DML scripts</div>
              </button>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Project Name</label>
            <input
              type="text"
              value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              placeholder={isDatabase ? 'e.g. prod-db migration to new-db' : 'e.g. my-service migration to v2'}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          {/* Source repo fields — only for non-database modes */}
          {!isDatabase && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Source Repository</label>
                <div className="flex gap-2 mb-3">
                  {(['url', 'path', 'existing'] as const).map(mode => (
                    <button
                      key={mode}
                      onClick={() => setForm({ ...form, source_mode: mode })}
                      className={`px-3 py-1.5 text-xs rounded-md ${
                        form.source_mode === mode
                          ? 'bg-indigo-100 text-indigo-700 font-medium'
                          : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                      }`}
                    >
                      {mode === 'url' ? 'Git URL' : mode === 'path' ? 'Local Path' : 'Existing Repo'}
                    </button>
                  ))}
                </div>

                {form.source_mode === 'url' && (
                  <input
                    type="text"
                    value={form.source_repo_url}
                    onChange={e => setForm({ ...form, source_repo_url: e.target.value })}
                    placeholder="https://github.com/org/repo.git"
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                )}
                {form.source_mode === 'path' && (
                  <input
                    type="text"
                    value={form.source_local_path}
                    onChange={e => setForm({ ...form, source_local_path: e.target.value })}
                    placeholder="/path/to/repo"
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                )}
                {form.source_mode === 'existing' && (
                  <select
                    value={form.source_repo_id}
                    onChange={e => setForm({ ...form, source_repo_id: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    <option value="">Select a repo...</option>
                    {existingRepos.map(r => (
                      <option key={r.id} value={r.id}>{r.url || r.local_path || r.id}</option>
                    ))}
                  </select>
                )}
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Branch</label>
                <input
                  type="text"
                  value={form.source_branch}
                  onChange={e => setForm({ ...form, source_branch: e.target.value })}
                  placeholder="main"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
            </>
          )}
        </div>
      )}

      {/* Step 2: Source DB (database mode) or Reference Repo (other modes) */}
      {step === 2 && isDatabase && (
        <div className="space-y-4">
          <h3 className="text-sm font-semibold text-gray-900">Source Database Connection</h3>
          <DatabaseConnectionForm
            prefix="source_db"
            values={{
              engine: form.source_db_engine,
              host: form.source_db_host,
              port: form.source_db_port,
              database: form.source_db_database,
              schema: form.source_db_schema,
              jdbc_url: form.source_db_jdbc_url,
              username: form.source_db_username,
            }}
            onChange={(field, value) => handleDbFieldChange('source_db', field, value)}
          />
        </div>
      )}

      {step === 2 && !isDatabase && (
        <div className="space-y-4">
          {isImprovement && (
            <div className="bg-blue-50 border border-blue-200 rounded-md p-3 text-xs text-blue-700">
              In improvement mode, a reference repo is optional. If provided, it will be used for
              additional comparison alongside the quality analysis.
            </div>
          )}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Reference Repository URL</label>
            <input
              type="text"
              value={form.reference_repo_url}
              onChange={e => setForm({ ...form, reference_repo_url: e.target.value })}
              placeholder="https://github.com/org/golden-template.git"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div className="relative">
            <div className="absolute inset-0 flex items-center"><div className="w-full border-t border-gray-200" /></div>
            <div className="relative flex justify-center text-sm"><span className="bg-white px-2 text-gray-400">or</span></div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Reference Local Path</label>
            <input
              type="text"
              value={form.reference_local_path}
              onChange={e => setForm({ ...form, reference_local_path: e.target.value })}
              placeholder="/path/to/golden-template"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Branch</label>
            <input
              type="text"
              value={form.reference_branch}
              onChange={e => setForm({ ...form, reference_branch: e.target.value })}
              placeholder="main"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Reference Folders <span className="text-gray-400 font-normal">(optional, comma-separated)</span>
            </label>
            <input
              type="text"
              value={form.reference_folders.join(', ')}
              onChange={e => setForm({ ...form, reference_folders: e.target.value.split(',').map(s => s.trim()).filter(Boolean) })}
              placeholder="src/main, k8s, docker"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
        </div>
      )}

      {/* Step 3: Destination DB (database mode) or Review (other modes) */}
      {step === 3 && isDatabase && (
        <div className="space-y-4">
          <div className="bg-blue-50 border border-blue-200 rounded-md p-3 text-xs text-blue-700">
            Destination database is optional. If provided, a full gap analysis between source and destination
            schemas will be performed.
          </div>
          <h3 className="text-sm font-semibold text-gray-900">Destination Database Connection</h3>
          <DatabaseConnectionForm
            prefix="dest_db"
            values={{
              engine: form.dest_db_engine,
              host: form.dest_db_host,
              port: form.dest_db_port,
              database: form.dest_db_database,
              schema: form.dest_db_schema,
              jdbc_url: form.dest_db_jdbc_url,
              username: form.dest_db_username,
            }}
            onChange={(field, value) => handleDbFieldChange('dest_db', field, value)}
          />
        </div>
      )}

      {step === 3 && !isDatabase && (
        <div className="space-y-4">
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Review Migration Project</h3>
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-gray-500">Mode</dt>
                <dd className={`font-medium capitalize ${isImprovement ? 'text-emerald-700' : 'text-indigo-700'}`}>
                  {form.migration_mode}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Name</dt>
                <dd className="text-gray-900 font-medium">{form.name}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Source</dt>
                <dd className="text-gray-900 truncate max-w-xs">
                  {form.source_mode === 'existing'
                    ? existingRepos.find(r => r.id === form.source_repo_id)?.url || form.source_repo_id
                    : form.source_repo_url || form.source_local_path}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Source Branch</dt>
                <dd className="text-gray-900">{form.source_branch}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Reference</dt>
                <dd className="text-gray-900 truncate max-w-xs">
                  {form.reference_repo_url || form.reference_local_path}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Reference Branch</dt>
                <dd className="text-gray-900">{form.reference_branch}</dd>
              </div>
              {form.reference_folders.length > 0 && (
                <div className="flex justify-between">
                  <dt className="text-gray-500">Folders</dt>
                  <dd className="text-gray-900">{form.reference_folders.join(', ')}</dd>
                </div>
              )}
            </dl>
          </div>
          <p className="text-xs text-gray-400">
            {isImprovement
              ? 'After creation, quality and improvement analysis will start automatically.'
              : 'After creation, stack analysis will start automatically on both repositories.'}
          </p>
        </div>
      )}

      {/* Step 4: Review (database mode only) */}
      {step === 4 && isDatabase && (
        <div className="space-y-4">
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Review Database Migration Project</h3>
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between">
                <dt className="text-gray-500">Mode</dt>
                <dd className="font-medium text-cyan-700">Database</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Name</dt>
                <dd className="text-gray-900 font-medium">{form.name}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-gray-500">Source DB</dt>
                <dd className="text-gray-900 truncate max-w-xs font-mono text-xs">
                  {form.source_db_jdbc_url || `${form.source_db_engine}://${form.source_db_host}:${form.source_db_port}/${form.source_db_database}`}
                </dd>
              </div>
              {(form.dest_db_host || form.dest_db_jdbc_url) && (
                <div className="flex justify-between">
                  <dt className="text-gray-500">Destination DB</dt>
                  <dd className="text-gray-900 truncate max-w-xs font-mono text-xs">
                    {form.dest_db_jdbc_url || `${form.dest_db_engine}://${form.dest_db_host}:${form.dest_db_port}/${form.dest_db_database}`}
                  </dd>
                </div>
              )}
            </dl>
          </div>
          <p className="text-xs text-gray-400">
            After creation, database schema introspection will start automatically.
          </p>
        </div>
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between mt-8">
        <button
          onClick={() => setStep((step - 1) as WizardStep)}
          disabled={step === 1}
          className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 disabled:opacity-30 disabled:cursor-not-allowed"
        >
          Back
        </button>
        {!isLastStep ? (
          <button
            onClick={() => setStep((step + 1) as WizardStep)}
            disabled={!canNext()}
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700 disabled:opacity-50"
          >
            Next
          </button>
        ) : (
          <button
            onClick={handleCreate}
            disabled={creating}
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700 disabled:opacity-50"
          >
            {creating ? 'Creating...' : 'Create & Analyze'}
          </button>
        )}
      </div>
    </div>
  );
}
