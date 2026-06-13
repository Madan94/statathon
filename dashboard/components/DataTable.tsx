'use client';

import { useState } from 'react';

interface DataTableProps {
  columns: string[];
  data: unknown[][];
  insights?: Record<string, { type?: string; semantic?: string; priority?: number }>;
}

export default function DataTable({ columns, data, insights = {} }: DataTableProps) {
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const totalPages = Math.ceil(data.length / pageSize);
  const pageData = data.slice((page - 1) * pageSize, page * pageSize);

  return (
    <div className="w-full overflow-x-auto">
      <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
        <thead className="bg-gray-50 dark:bg-gray-800">
          <tr>
            {columns.map((col, idx) => (
              <th
                key={idx}
                className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider dark:text-gray-300"
              >
                <div className="flex flex-col">
                  <span>{col}</span>
                  {insights[col] && (
                    <span className="text-xs text-gray-400 mt-1">
                      {insights[col].semantic && (
                        <span className="mr-2">{insights[col].semantic}</span>
                      )}
                      {insights[col].priority !== undefined && (
                        <span className="text-blue-500">Priority: {insights[col].priority.toFixed(2)}</span>
                      )}
                    </span>
                  )}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="bg-white divide-y divide-gray-200 dark:bg-gray-900 dark:divide-gray-700">
          {pageData.map((row, rowIdx) => (
            <tr key={rowIdx} className="hover:bg-gray-50 dark:hover:bg-gray-800">
              {row.map((cell, cellIdx) => (
                <td key={cellIdx} className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-gray-100">
                  {cell !== null && cell !== undefined ? String(cell) : <span className="text-gray-400">—</span>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md disabled:opacity-50 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600"
          >
            Previous
          </button>
          <span className="text-sm text-gray-700 dark:text-gray-300">
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md disabled:opacity-50 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

