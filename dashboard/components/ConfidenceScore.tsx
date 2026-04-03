'use client';

interface ConfidenceScoreProps {
  score: number;
  label?: string;
  size?: 'sm' | 'md' | 'lg';
}

export default function ConfidenceScore({ score, label, size = 'md' }: ConfidenceScoreProps) {
  const percentage = Math.round(score * 100);
  const colorClass =
    percentage >= 70
      ? 'bg-green-500'
      : percentage >= 40
        ? 'bg-yellow-500'
        : 'bg-red-500';

  const sizeClasses = {
    sm: 'h-2 text-xs',
    md: 'h-4 text-sm',
    lg: 'h-6 text-base',
  };

  return (
    <div className="w-full">
      {label && (
        <div className="flex justify-between mb-1">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">{label}</span>
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">{percentage}%</span>
        </div>
      )}
      <div className={`w-full bg-gray-200 rounded-full ${sizeClasses[size]}`}>
        <div
          className={`${colorClass} rounded-full transition-all duration-300 flex items-center justify-center text-white font-medium`}
          style={{ width: `${percentage}%` }}
        >
          {!label && <span>{percentage}%</span>}
        </div>
      </div>
    </div>
  );
}

