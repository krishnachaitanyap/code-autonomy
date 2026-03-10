'use client';

import { useState } from 'react';

interface CapacityFormProps {
  capacityCurrent: Record<string, any>;
  capacityTarget: Record<string, any>;
  onSave: (target: Record<string, any>) => void;
  saving?: boolean;
}

export default function CapacityForm({ capacityCurrent, capacityTarget, onSave, saving }: CapacityFormProps) {
  const [target, setTarget] = useState<Record<string, any>>(capacityTarget || {
    regions: ['us-east-1'],
    datacenters: [],
    replicas_per_service: 3,
    cpu_request: '500m',
    cpu_limit: '1000m',
    memory_request: '512Mi',
    memory_limit: '1Gi',
    scaling_policy: 'horizontal',
    min_replicas: 2,
    max_replicas: 10,
  });

  const updateField = (key: string, value: any) => {
    setTarget(prev => ({ ...prev, [key]: value }));
  };

  return (
    <div className="space-y-6">
      {/* Current Capacity (read-only) */}
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">Current Capacity (Auto-Detected)</h3>
        {(!capacityCurrent || Object.keys(capacityCurrent).length === 0) ? (
          <p className="text-sm text-gray-400">Run analysis first to detect current capacity.</p>
        ) : (
          <div className="space-y-2">
            <div className="text-sm">
              <span className="text-gray-500">Total Replicas:</span>{' '}
              <span className="font-medium">{capacityCurrent.total_replicas || 0}</span>
            </div>
            {(capacityCurrent.services || []).length > 0 && (
              <div>
                <span className="text-sm text-gray-500">Services:</span>
                <div className="mt-1 space-y-1">
                  {(capacityCurrent.services || []).map((svc: any, i: number) => (
                    <div key={i} className="flex items-center justify-between text-sm py-1 px-2 bg-gray-50 rounded">
                      <span className="text-gray-700">{svc.name || svc.kind}</span>
                      <span className="text-gray-500">replicas: {svc.replicas}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Target Capacity (editable) */}
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">Target Capacity</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Regions (comma-separated)</label>
            <input
              type="text"
              value={(target.regions || []).join(', ')}
              onChange={e => updateField('regions', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Data Centers (comma-separated)</label>
            <input
              type="text"
              value={(target.datacenters || []).join(', ')}
              onChange={e => updateField('datacenters', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Replicas per Service</label>
            <input
              type="number"
              value={target.replicas_per_service || 3}
              onChange={e => updateField('replicas_per_service', parseInt(e.target.value) || 1)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Scaling Policy</label>
            <select
              value={target.scaling_policy || 'horizontal'}
              onChange={e => updateField('scaling_policy', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="horizontal">Horizontal Pod Autoscaler</option>
              <option value="vertical">Vertical Pod Autoscaler</option>
              <option value="keda">KEDA Event-Driven</option>
              <option value="none">None (Fixed)</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">CPU Request</label>
            <input
              type="text"
              value={target.cpu_request || '500m'}
              onChange={e => updateField('cpu_request', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">CPU Limit</label>
            <input
              type="text"
              value={target.cpu_limit || '1000m'}
              onChange={e => updateField('cpu_limit', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Memory Request</label>
            <input
              type="text"
              value={target.memory_request || '512Mi'}
              onChange={e => updateField('memory_request', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Memory Limit</label>
            <input
              type="text"
              value={target.memory_limit || '1Gi'}
              onChange={e => updateField('memory_limit', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Min Replicas (HPA)</label>
            <input
              type="number"
              value={target.min_replicas || 2}
              onChange={e => updateField('min_replicas', parseInt(e.target.value) || 1)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Max Replicas (HPA)</label>
            <input
              type="number"
              value={target.max_replicas || 10}
              onChange={e => updateField('max_replicas', parseInt(e.target.value) || 1)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
        </div>
        <div className="mt-4 flex justify-end">
          <button
            onClick={() => onSave(target)}
            disabled={saving}
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700 disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save Target Capacity'}
          </button>
        </div>
      </div>
    </div>
  );
}
