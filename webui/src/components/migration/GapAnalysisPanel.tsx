'use client';

import { useState } from 'react';

interface GapAnalysisPanelProps {
  sourceProfile: Record<string, any>;
  referenceProfile: Record<string, any>;
  gapAnalysis: Record<string, any>;
  improvementAnalysis?: Record<string, any>;
  migrationMode?: string;
}

function GapSection({ title, gaps, renderGap }: { title: string; gaps: any[]; renderGap: (g: any, i: number) => React.ReactNode }) {
  if (!gaps || gaps.length === 0) return null;
  return (
    <div className="mb-4">
      <h4 className="text-sm font-medium text-gray-700 mb-2">{title} ({gaps.length})</h4>
      <div className="space-y-1">
        {gaps.map((g, i) => renderGap(g, i))}
      </div>
    </div>
  );
}

export default function GapAnalysisPanel({ sourceProfile, referenceProfile, gapAnalysis, improvementAnalysis, migrationMode }: GapAnalysisPanelProps) {
  const summary = gapAnalysis?.summary || {};
  const categoriesWithGaps = gapAnalysis?.categories_with_gaps || [];
  const isImprovement = migrationMode === 'improvement';
  const isDatabase = migrationMode === 'database';
  const improvementSummary = improvementAnalysis?.summary || {};
  const hasReference = Object.keys(referenceProfile || {}).length > 0;

  // All gap category indicators
  const standardCategories = [
    'technology', 'dependencies', 'k8s', 'docker', 'config', 'cicd', 'observability', 'security',
    'test_coverage', 'code_quality', 'performance', 'structure', 'error_handling', 'api_documentation',
  ];
  const databaseCategories = [
    'database_tables', 'database_collections', 'database_columns', 'database_indexes',
    'database_types', 'database_views', 'database_constraints', 'database_nosql',
  ];
  const displayCategories = isDatabase ? databaseCategories : standardCategories;

  return (
    <div className="space-y-6">
      {/* Summary */}
      {isDatabase ? (
        <div className="grid grid-cols-2 lg:grid-cols-6 gap-3">
          <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-gray-900">{summary.total_gaps || 0}</div>
            <div className="text-xs text-gray-500">Total Gaps</div>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-cyan-600">{(summary.table_gap_count || 0) + (summary.collection_gap_count || 0)}</div>
            <div className="text-xs text-gray-500">{(summary.collection_gap_count || 0) > 0 ? 'Collection Gaps' : 'Table Gaps'}</div>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-blue-600">{summary.column_gap_count || 0}</div>
            <div className="text-xs text-gray-500">Field Gaps</div>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-purple-600">{summary.type_mapping_gap_count || 0}</div>
            <div className="text-xs text-gray-500">Type Mismatches</div>
          </div>
          {summary.cross_engine && (
            <div className="bg-white border border-violet-200 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-violet-600">SQL/NoSQL</div>
              <div className="text-xs text-gray-500">Cross-Engine</div>
            </div>
          )}
          <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-emerald-600">{improvementSummary.areas_needing_improvement || 0}</div>
            <div className="text-xs text-gray-500">Improvement Areas</div>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-gray-900">{summary.total_gaps || 0}</div>
            <div className="text-xs text-gray-500">Total Gaps</div>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-blue-600">{summary.technology_gap_count || 0}</div>
            <div className="text-xs text-gray-500">Technology</div>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-purple-600">{summary.dependency_gap_count || 0}</div>
            <div className="text-xs text-gray-500">Dependencies</div>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-orange-600">{summary.k8s_gap_count || 0}</div>
            <div className="text-xs text-gray-500">Kubernetes</div>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-emerald-600">{improvementSummary.areas_needing_improvement || 0}</div>
            <div className="text-xs text-gray-500">Improvement Areas</div>
          </div>
        </div>
      )}

      {/* Categories indicator */}
      <div className="flex flex-wrap gap-2">
        {displayCategories.map(cat => (
          <span
            key={cat}
            className={`px-2.5 py-1 rounded-full text-xs font-medium ${
              categoriesWithGaps.includes(cat)
                ? 'bg-red-100 text-red-700'
                : 'bg-green-100 text-green-700'
            }`}
          >
            {categoriesWithGaps.includes(cat) ? '\u2717' : '\u2713'} {cat.replace(/_/g, ' ')}
          </span>
        ))}
      </div>

      {/* Schema views for database mode */}
      {isDatabase && (
        <div className={`grid grid-cols-1 ${hasReference ? 'lg:grid-cols-2' : ''} gap-4`}>
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Source Schema</h3>
            <DatabaseSchemaView schema={sourceProfile} />
          </div>
          {hasReference && (
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <h3 className="text-sm font-semibold text-gray-900 mb-3">Destination Schema</h3>
              <DatabaseSchemaView schema={referenceProfile} />
            </div>
          )}
        </div>
      )}

      {/* Side-by-side profiles for non-database mode */}
      {!isDatabase && (
        <div className={`grid grid-cols-1 ${hasReference ? 'lg:grid-cols-2' : ''} gap-4`}>
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">
              {isImprovement ? 'Repository Profile' : 'Source Profile'}
            </h3>
            <ProfileSummary profile={sourceProfile} />
          </div>
          {hasReference && (
            <div className="bg-white border border-gray-200 rounded-lg p-4">
              <h3 className="text-sm font-semibold text-gray-900 mb-3">Reference Profile</h3>
              <ProfileSummary profile={referenceProfile} />
            </div>
          )}
        </div>
      )}

      {/* Improvement Analysis */}
      {improvementAnalysis && Object.keys(improvementAnalysis).length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">
            {isDatabase ? 'Database Improvement Analysis' : 'Improvement Analysis'}
          </h3>
          <div className="space-y-3">
            {isDatabase ? (
              <>
                <ImprovementArea title="Indexing" data={improvementAnalysis.indexing} color="cyan" />
                <ImprovementArea title="Constraints" data={improvementAnalysis.constraints} color="violet" />
                <ImprovementArea title="Schema Design" data={improvementAnalysis.schema_design} color="amber" />
              </>
            ) : (
              <>
                <ImprovementArea title="Test Coverage" data={improvementAnalysis.test_coverage} color="emerald" />
                <ImprovementArea title="Code Quality" data={improvementAnalysis.code_quality} color="pink" />
                <ImprovementArea title="Performance" data={improvementAnalysis.performance} color="amber" />
                <ImprovementArea title="Project Structure" data={improvementAnalysis.structure} color="violet" />
                <ImprovementArea title="Error Handling" data={improvementAnalysis.error_handling} color="rose" />
                <ImprovementArea title="API Documentation" data={improvementAnalysis.api_documentation} color="sky" />
              </>
            )}
          </div>
        </div>
      )}

      {/* Gap details */}
      {isDatabase ? (
        /* Database gap details */
        (summary.total_gaps || 0) > 0 && (
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Database Gap Details</h3>

            <GapSection
              title="Table Gaps"
              gaps={gapAnalysis?.table_gaps || []}
              renderGap={(g, i) => (
                <div key={i} className="flex items-center justify-between text-sm py-1 px-2 bg-cyan-50 rounded">
                  <span className="text-gray-700 font-mono text-xs">{g.table}</span>
                  <span className={`text-xs ${g.status === 'missing_in_destination' ? 'text-red-500' : 'text-yellow-600'}`}>
                    {g.status.replace(/_/g, ' ')}
                  </span>
                </div>
              )}
            />

            <GapSection
              title="Collection Gaps"
              gaps={gapAnalysis?.collection_gaps || []}
              renderGap={(g, i) => (
                <div key={i} className="flex items-center justify-between text-sm py-1 px-2 bg-violet-50 rounded">
                  <span className="text-gray-700 font-mono text-xs">{g.collection}</span>
                  <span className={`text-xs ${g.status === 'missing_in_destination' ? 'text-red-500' : 'text-yellow-600'}`}>
                    {g.status.replace(/_/g, ' ')}
                  </span>
                </div>
              )}
            />

            <GapSection
              title="Column Gaps"
              gaps={gapAnalysis?.column_gaps || []}
              renderGap={(g, i) => (
                <div key={i} className="flex items-center justify-between text-sm py-1 px-2 bg-blue-50 rounded">
                  <span className="text-gray-700 font-mono text-xs">{g.table}.{g.column}</span>
                  <span className="text-xs text-red-500">{g.status.replace(/_/g, ' ')}</span>
                </div>
              )}
            />

            <GapSection
              title="Type Mapping Gaps"
              gaps={gapAnalysis?.type_mapping_gaps || []}
              renderGap={(g, i) => (
                <div key={i} className="flex items-center justify-between text-sm py-1 px-2 bg-purple-50 rounded">
                  <span className="text-gray-700 font-mono text-xs">{g.table}.{g.column}</span>
                  <span className="text-xs text-yellow-600">{g.source_type} &rarr; {g.destination_type}</span>
                </div>
              )}
            />

            <GapSection
              title="Index Gaps"
              gaps={gapAnalysis?.index_gaps || []}
              renderGap={(g, i) => (
                <div key={i} className="flex items-center justify-between text-sm py-1 px-2 bg-orange-50 rounded">
                  <span className="text-gray-700 font-mono text-xs">{g.table}.{g.name}</span>
                  <span className="text-xs text-red-500">{g.status.replace(/_/g, ' ')}</span>
                </div>
              )}
            />

            <GapSection
              title="View Gaps"
              gaps={gapAnalysis?.view_gaps || []}
              renderGap={(g, i) => (
                <div key={i} className="flex items-center justify-between text-sm py-1 px-2 bg-teal-50 rounded">
                  <span className="text-gray-700 font-mono text-xs">{g.view}</span>
                  <span className="text-xs text-red-500">{g.status.replace(/_/g, ' ')}</span>
                </div>
              )}
            />
          </div>
        )
      ) : (
        /* Standard gap details */
        (hasReference || (summary.total_gaps || 0) > 0) && (
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Gap Details</h3>

            <GapSection
              title="Technology Gaps"
              gaps={gapAnalysis?.technology_gaps || []}
              renderGap={(g, i) => (
                <div key={i} className="flex items-center gap-2 text-sm py-1 px-2 bg-red-50 rounded">
                  <span className="text-red-500 text-xs">missing</span>
                  <span className="text-gray-700">{g.tech}</span>
                </div>
              )}
            />

            <GapSection
              title="Dependency Gaps"
              gaps={gapAnalysis?.dependency_gaps || []}
              renderGap={(g, i) => (
                <div key={i} className="flex items-center justify-between text-sm py-1 px-2 bg-purple-50 rounded">
                  <span className="text-gray-700 font-mono text-xs">{g.artifact}</span>
                  <span className={`text-xs ${g.status === 'missing' ? 'text-red-500' : 'text-yellow-600'}`}>
                    {g.status === 'missing' ? 'missing' : `${g.source_version} -> ${g.reference_version}`}
                  </span>
                </div>
              )}
            />

            <GapSection
              title="Kubernetes Gaps"
              gaps={gapAnalysis?.k8s_gaps || []}
              renderGap={(g, i) => (
                <div key={i} className="flex items-center justify-between text-sm py-1 px-2 bg-orange-50 rounded">
                  <span className="text-gray-700">{g.kind}</span>
                  <span className={`text-xs ${g.status === 'missing' ? 'text-red-500' : 'text-yellow-600'}`}>
                    {g.status}
                  </span>
                </div>
              )}
            />

            <GapSection
              title="Config Gaps"
              gaps={gapAnalysis?.config_gaps || []}
              renderGap={(g, i) => (
                <div key={i} className="flex items-center justify-between text-sm py-1 px-2 bg-teal-50 rounded">
                  <span className="text-gray-700 font-mono text-xs">{g.key}</span>
                  <span className={`text-xs ${g.status === 'missing' ? 'text-red-500' : 'text-yellow-600'}`}>
                    {g.status}
                  </span>
                </div>
              )}
            />

            {(summary.total_gaps || 0) === 0 && (
              <p className="text-sm text-gray-500 text-center py-4">No gaps detected. Profiles are aligned.</p>
            )}
          </div>
        )
      )}
    </div>
  );
}

function DatabaseSchemaView({ schema }: { schema: Record<string, any> }) {
  const [expandedEntities, setExpandedEntities] = useState<Set<string>>(new Set());

  if (!schema || Object.keys(schema).length === 0) {
    return <p className="text-sm text-gray-400">Not analyzed yet</p>;
  }

  const isNoSQL = schema.db_type === 'nosql';
  const tables: any[] = schema.tables || [];
  const collections: any[] = schema.collections || [];
  const views: any[] = schema.views || [];
  const indexes: any[] = schema.indexes || [];
  const entities = isNoSQL ? collections : tables;
  const entityLabel = isNoSQL ? 'collections' : 'tables';
  const fieldLabel = isNoSQL ? 'fields' : 'cols';

  const toggleEntity = (name: string) => {
    setExpandedEntities(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  return (
    <div className="space-y-3 text-sm">
      <div className="flex items-center gap-4 text-xs text-gray-500">
        <span>Engine: <span className="font-medium text-gray-700">{schema.engine || 'unknown'}</span></span>
        <span>Database: <span className="font-medium text-gray-700">{schema.database || '-'}</span></span>
        <span>Mode: <span className="font-medium text-gray-700">{schema.introspection_mode || 'static'}</span></span>
        {isNoSQL && <span className="px-1.5 py-0.5 bg-violet-100 text-violet-700 rounded text-[10px] font-medium">NoSQL</span>}
      </div>

      <div className="flex items-center gap-4 text-xs text-gray-500">
        <span>{entities.length} {entityLabel}</span>
        {!isNoSQL && <span>{views.length} views</span>}
        <span>{indexes.length} indexes</span>
      </div>

      {entities.length > 0 && (
        <div className="border border-gray-200 rounded-lg divide-y divide-gray-100">
          {entities.map((entity: any) => {
            const fields = entity.fields || entity.columns || [];
            const fieldCount = entity.field_count || entity.column_count || fields.length;
            return (
              <div key={entity.name}>
                <button
                  onClick={() => toggleEntity(entity.name)}
                  className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-gray-50"
                >
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-gray-800">{entity.name}</span>
                    {entity.estimated_count !== undefined && entity.estimated_count > 0 && (
                      <span className="text-[10px] text-gray-400">~{entity.estimated_count.toLocaleString()} docs</span>
                    )}
                  </div>
                  <span className="text-[10px] text-gray-400">{fieldCount} {fieldLabel}</span>
                </button>
                {expandedEntities.has(entity.name) && fields.length > 0 && (
                  <div className="px-3 pb-2">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-gray-400">
                          <th className="text-left font-normal pb-1">{isNoSQL ? 'Field' : 'Column'}</th>
                          <th className="text-left font-normal pb-1">Type</th>
                          <th className="text-center font-normal pb-1">PK</th>
                          <th className="text-center font-normal pb-1">Nullable</th>
                        </tr>
                      </thead>
                      <tbody>
                        {fields.map((f: any) => (
                          <tr key={f.name} className="border-t border-gray-50">
                            <td className="py-0.5 font-mono text-gray-700">{f.name}</td>
                            <td className="py-0.5 text-gray-500">{f.type}</td>
                            <td className="py-0.5 text-center">{f.primary_key ? <span className="text-amber-500">PK</span> : ''}</td>
                            <td className="py-0.5 text-center text-gray-400">{f.nullable ? 'yes' : 'no'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ImprovementArea({ title, data, color }: { title: string; data?: Record<string, any>; color: string }) {
  if (!data || Object.keys(data).length === 0) return null;
  const needs = data.needs_improvement;
  const issues: string[] = data.issues || [];

  return (
    <div className={`border rounded-lg p-3 ${needs ? `border-${color}-200 bg-${color}-50/30` : 'border-gray-200'}`}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm font-medium text-gray-800">{title}</span>
        <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
          needs ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'
        }`}>
          {needs ? 'Needs Work' : 'OK'}
        </span>
      </div>
      {issues.length > 0 && (
        <ul className="space-y-1 mt-2">
          {issues.map((issue, i) => (
            <li key={i} className="text-xs text-gray-600 flex items-start gap-1.5">
              <span className="text-red-400 mt-0.5 shrink-0">&bull;</span>
              {issue}
            </li>
          ))}
        </ul>
      )}
      {/* Extra detail for test coverage */}
      {data.test_ratio !== undefined && (
        <div className="flex items-center gap-3 mt-2 text-[10px] text-gray-500">
          <span>Source files: {data.source_file_count}</span>
          <span>Test files: {data.test_file_count}</span>
          <span>Ratio: {data.test_ratio}</span>
        </div>
      )}
    </div>
  );
}

function ProfileSummary({ profile }: { profile: Record<string, any> }) {
  if (!profile || Object.keys(profile).length === 0) {
    return <p className="text-sm text-gray-400">Not analyzed yet</p>;
  }

  const techs = profile.technologies || {};
  const deps = profile.dependencies || [];
  const k8s = profile.k8s_resources || [];

  return (
    <div className="space-y-3 text-sm">
      <div>
        <span className="text-gray-500">App Type:</span>{' '}
        <span className="font-medium">{profile.app_type || 'unknown'}</span>
      </div>
      {Object.keys(techs).length > 0 && (
        <div>
          <span className="text-gray-500">Technologies:</span>
          <div className="flex flex-wrap gap-1 mt-1">
            {Object.entries(techs).map(([cat, items]) =>
              (items as string[]).map((t, i) => (
                <span key={`${cat}-${i}`} className="px-1.5 py-0.5 bg-gray-100 rounded text-[10px] text-gray-600">
                  {t}
                </span>
              ))
            )}
          </div>
        </div>
      )}
      <div>
        <span className="text-gray-500">Dependencies:</span>{' '}
        <span className="font-medium">{deps.length}</span>
      </div>
      <div>
        <span className="text-gray-500">K8s Resources:</span>{' '}
        <span className="font-medium">{k8s.length}</span>
      </div>
    </div>
  );
}
