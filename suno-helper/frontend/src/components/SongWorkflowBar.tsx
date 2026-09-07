import { WorkflowStepInfo } from "../lib/songWorkflow";

interface Props {
  steps: WorkflowStepInfo[];
  onStepClick?: (stepId: string) => void;
}

export default function SongWorkflowBar({ steps, onStepClick }: Props) {
  return (
    <div className="song-workflow-bar">
      {steps.map((step, index) => (
        <div key={step.id} className="song-workflow-item">
          <button
            type="button"
            className={`song-workflow-btn ${step.active ? "active" : ""} ${step.done ? "done" : ""}`}
            onClick={() => onStepClick?.(step.id)}
            title={`클릭하면 「${step.label}」 편집 화면으로 이동합니다`}
            aria-label={`${step.label} 단계로 이동`}
          >
            <span className={`song-workflow-step ${step.active ? "active" : ""} ${step.done ? "done" : ""}`}>
              {step.done ? "✓" : index + 1}
            </span>
            <span className={`song-workflow-label ${step.active ? "active" : ""}`}>
              {step.label}
            </span>
          </button>
          {index < steps.length - 1 && <span className="song-workflow-arrow">→</span>}
        </div>
      ))}
    </div>
  );
}
