import React, { useState } from 'react';
import { useKeycloak } from '@react-keycloak/web';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8001';

interface ReportItem {
  day: string;
  prosthesis_id: string;
  product_model: string;
  events_count: number;
  avg_reaction_time_ms: number;
  p95_reaction_time_ms: number;
  avg_battery_level: number;
  min_battery_level: number;
  avg_signal_quality: number;
}

interface ClientProfile {
  full_name: string;
  email: string;
  city: string;
  orders_count: number;
  total_spent: number;
  last_order_date: string | null;
}

interface ReportResponse {
  user_id: string;
  profile: ClientProfile | null;
  period_from: string | null;
  period_to: string;
  processed_until: string;
  items: ReportItem[];
}

const extractErrorMessage = (body: unknown, status: number): string => {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === 'string') {
      return detail;
    }
    if (detail && typeof detail === 'object' && 'message' in detail) {
      return String((detail as { message: unknown }).message);
    }
  }
  return `Request failed with status ${status}`;
};

const ReportPage: React.FC = () => {
  const { keycloak, initialized } = useKeycloak();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ReportResponse | null>(null);

  const downloadReport = async () => {
    if (!keycloak?.authenticated || !keycloak.subject) {
      setError('Not authenticated');
      return;
    }

    try {
      setLoading(true);
      setError(null);
      setReport(null);

      await keycloak.updateToken(30);

      const response = await fetch(`${API_URL}/reports/${keycloak.subject}`, {
        headers: {
          'Authorization': `Bearer ${keycloak.token}`
        }
      });

      if (!response.ok) {
        const body: unknown = await response.json().catch(() => null);
        throw new Error(extractErrorMessage(body, response.status));
      }

      const data = (await response.json()) as ReportResponse;
      setReport(data);

      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: 'application/json'
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `report-${data.user_id}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  if (!initialized) {
    return <div>Loading...</div>;
  }

  if (!keycloak.authenticated) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
        <button
          onClick={() => keycloak.login()}
          className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
        >
          Login
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
      <div className="p-8 bg-white rounded-lg shadow-md">
        <h1 className="text-2xl font-bold mb-6">Usage Reports</h1>

        <button
          onClick={downloadReport}
          disabled={loading}
          className={`px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 ${
            loading ? 'opacity-50 cursor-not-allowed' : ''
          }`}
        >
          {loading ? 'Generating Report...' : 'Download Report'}
        </button>

        {error && (
          <div className="mt-4 p-4 bg-red-100 text-red-700 rounded">
            {error}
          </div>
        )}

        {report && (
          <div className="mt-4 p-4 bg-gray-50 rounded">
            <p>Period: {report.period_from ?? 'start'} — {report.period_to}</p>
            <p>Processed until: {report.processed_until}</p>
            <p>Days: {report.items.length}</p>
            {report.profile && (
              <p>
                {report.profile.full_name} ({report.profile.email})
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default ReportPage;
