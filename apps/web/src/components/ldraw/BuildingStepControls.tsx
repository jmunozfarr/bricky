interface BuildingStepControlsProps {
  selectedStep: number;
  stepCount: number;
  onStepChange: (step: number) => void;
  onResetCamera: () => void;
}

export function BuildingStepControls({
  selectedStep,
  stepCount,
  onStepChange,
  onResetCamera,
}: BuildingStepControlsProps) {
  if (stepCount <= 1) {
    return (
      <div className="viewer-controls viewer-controls--single">
        <p>No building steps</p>
        <button type="button" onClick={onResetCamera}>
          Reset camera
        </button>
      </div>
    );
  }

  const isFirstStep = selectedStep === 0;
  const isLastStep = selectedStep === stepCount - 1;

  return (
    <div className="viewer-controls">
      <div className="step-actions" aria-label="Building step navigation">
        <button
          type="button"
          onClick={() => onStepChange(selectedStep - 1)}
          disabled={isFirstStep}
          aria-label="Show previous building step"
        >
          Previous
        </button>
        <output className="step-indicator" aria-live="polite">
          Step {selectedStep + 1} of {stepCount}
        </output>
        <button
          type="button"
          onClick={() => onStepChange(selectedStep + 1)}
          disabled={isLastStep}
          aria-label="Show next building step"
        >
          Next
        </button>
      </div>

      <label className="step-range">
        <span>Select building step</span>
        <input
          type="range"
          min="0"
          max={stepCount - 1}
          step="1"
          value={selectedStep}
          onChange={(event) => onStepChange(event.currentTarget.valueAsNumber)}
        />
      </label>

      <div className="viewer-secondary-actions">
        <button type="button" onClick={() => onStepChange(stepCount - 1)} disabled={isLastStep}>
          Show complete model
        </button>
        <button type="button" onClick={onResetCamera}>
          Reset camera
        </button>
      </div>
    </div>
  );
}
