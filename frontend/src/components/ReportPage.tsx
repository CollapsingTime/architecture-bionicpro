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

interface ErrorDetail {
  message?: string;
  processed_until?: string;
}

const readError = async (
  response: Response
): Promise<{ message: string; processedUntil?: string }> => {
  const body: unknown = await response.json().catch(() => null);
  let message = '';
  let processedUntil: string | undefined;

  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === 'string') {
      message = detail;
    } else if (detail && typeof detail === 'object') {
      const parsed = detail as ErrorDetail;
      message = parsed.message ?? '';
      processedUntil = parsed.processed_until;
    }
  }

  switch (response.status) {
    case 401:
      return { message: 'Сессия истекла. Выполните вход повторно' };
    case 403:
      return { message: message || 'Доступ к чужому отчету запрещен' };
    case 409:
      return {
        message: message || 'Запрошенный период ещё не обработан',
        processedUntil
      };
    case 422:
      return { message: message || 'Некорректный период отчета' };
    case 503:
      return { message: message || 'Данные отчета ещё не готовы' };
    default:
      return {
        message: message || `Не удалось получить отчет (код ${response.status})`
      };
  }
};

const ReportPage: React.FC = () => {
  const { keycloak, initialized } = useKeycloak();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ReportResponse | null>(null);

  const getReport = async () => {
    if (!keycloak?.authenticated || !keycloak.subject) {
      setError('Необходимо войти в систему');
      return;
    }

    try {
      setLoading(true);
      setError(null);
      setReport(null);

      await keycloak.updateToken(30);

      const response = await fetch(`${API_URL}/reports/${keycloak.subject}`, {
        headers: {
          Authorization: `Bearer ${keycloak.token}`
        }
      });

      if (!response.ok) {
        const { message, processedUntil } = await readError(response);
        const suffix = processedUntil ? ` (обработано по: ${processedUntil})` : '';
        throw new Error(`${message}${suffix}`);
      }

      setReport((await response.json()) as ReportResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось получить отчет');
    } finally {
      setLoading(false);
    }
  };

  const downloadReport = () => {
    if (!report) {
      return;
    }
    const blob = new Blob([JSON.stringify(report, null, 2)], {
      type: 'application/json'
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `report-${report.user_id}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  if (!initialized) {
    return <div>Loading...</div>;
  }

  if (!keycloak.authenticated) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-gray-100">
        <button
          onClick={() => keycloak.login()}
          className="rounded bg-blue-500 px-4 py-2 text-white hover:bg-blue-600"
        >
          Login
        </button>
      </div>
    );
  }

  const username =
    (keycloak.tokenParsed?.preferred_username as string | undefined) ||
    keycloak.subject;

  return (
    <div className="flex min-h-screen flex-col items-center bg-gray-100 p-8">
      <div className="w-full max-w-6xl rounded-lg bg-white p-8 shadow-md">
        <h1 className="mb-2 text-2xl font-bold">Отчет о работе протеза</h1>
        {username && (
          <p className="mb-6 text-sm text-gray-600">Вы вошли как: {username}</p>
        )}

        <button
          onClick={() => void getReport()}
          disabled={loading}
          className={`rounded bg-blue-500 px-4 py-2 text-white hover:bg-blue-600 ${
            loading ? 'cursor-not-allowed opacity-50' : ''
          }`}
        >
          {loading ? 'Получаем отчет...' : 'Получить отчет'}
        </button>

        {error && (
          <div className="mt-4 rounded bg-red-100 p-4 text-red-700">
            {error}
          </div>
        )}

        {report && (
          <div className="mt-6">
            <div className="mb-6 grid gap-2 rounded bg-gray-50 p-4 text-sm">
              <p>
                <strong>Период:</strong> {report.period_from ?? 'начало'} —{' '}
                {report.period_to}
              </p>
              <p>
                <strong>Обработано по:</strong> {report.processed_until}
              </p>
              {report.profile && (
                <>
                  <p>
                    <strong>Пользователь:</strong> {report.profile.full_name} (
                    {report.profile.email})
                  </p>
                  <p>
                    <strong>Город:</strong> {report.profile.city}
                  </p>
                  <p>
                    <strong>Заказов:</strong> {report.profile.orders_count},
                    сумма: {report.profile.total_spent.toLocaleString('ru-RU')}
                  </p>
                </>
              )}
            </div>

            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold">Данные телеметрии</h2>
              <button
                onClick={downloadReport}
                className="rounded border border-blue-500 px-4 py-2 text-blue-600 hover:bg-blue-50"
              >
                Скачать JSON
              </button>
            </div>

            {report.items.length === 0 ? (
              <p className="text-gray-600">
                За обработанный период данных нет.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b bg-gray-50">
                      <th className="p-2">Дата</th>
                      <th className="p-2">Протез</th>
                      <th className="p-2">Модель</th>
                      <th className="p-2">События</th>
                      <th className="p-2">Ср. реакция, мс</th>
                      <th className="p-2">P95 реакции, мс</th>
                      <th className="p-2">Ср. батарея, %</th>
                      <th className="p-2">Мин. батарея, %</th>
                      <th className="p-2">Качество сигнала</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.items.map((item) => (
                      <tr
                        key={`${item.prosthesis_id}-${item.day}`}
                        className="border-b"
                      >
                        <td className="p-2">{item.day}</td>
                        <td className="p-2">{item.prosthesis_id}</td>
                        <td className="p-2">{item.product_model}</td>
                        <td className="p-2">{item.events_count}</td>
                        <td className="p-2">
                          {item.avg_reaction_time_ms.toFixed(1)}
                        </td>
                        <td className="p-2">
                          {item.p95_reaction_time_ms.toFixed(1)}
                        </td>
                        <td className="p-2">
                          {item.avg_battery_level.toFixed(1)}
                        </td>
                        <td className="p-2">
                          {item.min_battery_level.toFixed(1)}
                        </td>
                        <td className="p-2">
                          {item.avg_signal_quality.toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default ReportPage;
