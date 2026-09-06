import { WorkflowStepInfo } from "../lib/songWorkflow";

interface Props {
  steps: WorkflowStepInfo[];
}

export default function SongWorkflowBar({ steps }: Props) {
  return (
    <div className="song-workflow-bar">
      {steps.map((step, index) => (
        <div key={step.id} className="song-workflow-item">
          <span
            className={`song-workflow-step ${step.active ? "active" : ""} ${step.done ? "done" : ""}`}
          >
            {step.done ? "✓" : index + 1}
          </span>
          <span className={`song-workflow-label ${step.active ? "active" : ""}`}>
            {step.label}
          </span>
          {index < steps.length - 1 && <span className="song-workflow-arrow">→</span>}
        </div>
      ))}
    </div>
  );
}
