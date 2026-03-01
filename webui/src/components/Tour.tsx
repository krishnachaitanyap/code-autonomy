'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTour } from './TourProvider';

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

export default function Tour() {
  const { isActive, currentStep, steps, nextStep, prevStep, endTour } = useTour();
  const [targetRect, setTargetRect] = useState<Rect | null>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  const step = steps[currentStep];
  const isFirst = currentStep === 0;
  const isLast = currentStep === steps.length - 1;

  const updatePosition = useCallback(() => {
    if (!step) return;
    const el = document.querySelector(step.target);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      // Small delay to let scroll finish
      setTimeout(() => {
        const rect = el.getBoundingClientRect();
        setTargetRect({
          top: rect.top + window.scrollY,
          left: rect.left + window.scrollX,
          width: rect.width,
          height: rect.height,
        });
      }, 300);
    } else {
      // If target not found, show tooltip in center
      setTargetRect(null);
    }
  }, [step]);

  useEffect(() => {
    if (!isActive) return;
    updatePosition();

    window.addEventListener('resize', updatePosition);
    return () => window.removeEventListener('resize', updatePosition);
  }, [isActive, currentStep, updatePosition]);

  // Keyboard navigation
  useEffect(() => {
    if (!isActive) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'ArrowRight' || e.key === 'Enter') nextStep();
      else if (e.key === 'ArrowLeft') prevStep();
      else if (e.key === 'Escape') endTour();
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [isActive, nextStep, prevStep, endTour]);

  if (!isActive || !step) return null;

  // Calculate tooltip position
  const placement = step.placement || 'bottom';
  const pad = 12; // padding around highlighted element
  const tooltipOffset = 16;

  let tooltipStyle: React.CSSProperties = {};
  let arrowClass = '';

  if (targetRect) {
    const centerX = targetRect.left + targetRect.width / 2;

    if (placement === 'bottom') {
      tooltipStyle = {
        top: targetRect.top + targetRect.height + pad + tooltipOffset,
        left: Math.max(16, centerX - 180),
      };
      arrowClass = 'tour-arrow-top';
    } else if (placement === 'top') {
      tooltipStyle = {
        top: targetRect.top - pad - tooltipOffset,
        left: Math.max(16, centerX - 180),
        transform: 'translateY(-100%)',
      };
      arrowClass = 'tour-arrow-bottom';
    } else if (placement === 'right') {
      tooltipStyle = {
        top: targetRect.top + targetRect.height / 2 - 60,
        left: targetRect.left + targetRect.width + pad + tooltipOffset,
      };
      arrowClass = 'tour-arrow-left';
    } else {
      tooltipStyle = {
        top: targetRect.top + targetRect.height / 2 - 60,
        left: targetRect.left - pad - tooltipOffset,
        transform: 'translateX(-100%)',
      };
      arrowClass = 'tour-arrow-right';
    }
  } else {
    // Center on screen
    tooltipStyle = {
      top: '50%',
      left: '50%',
      transform: 'translate(-50%, -50%)',
    };
  }

  // Build clip-path to create the spotlight hole
  const clipPath = targetRect
    ? `polygon(
        0% 0%, 0% 100%,
        ${targetRect.left - pad}px 100%,
        ${targetRect.left - pad}px ${targetRect.top - pad}px,
        ${targetRect.left + targetRect.width + pad}px ${targetRect.top - pad}px,
        ${targetRect.left + targetRect.width + pad}px ${targetRect.top + targetRect.height + pad}px,
        ${targetRect.left - pad}px ${targetRect.top + targetRect.height + pad}px,
        ${targetRect.left - pad}px 100%,
        100% 100%, 100% 0%
      )`
    : undefined;

  return (
    <>
      {/* Overlay with spotlight cutout */}
      <div
        className="tour-overlay"
        style={{ clipPath }}
        onClick={endTour}
      />

      {/* Highlight border around target */}
      {targetRect && (
        <div
          className="tour-highlight"
          style={{
            position: 'absolute',
            top: targetRect.top - pad,
            left: targetRect.left - pad,
            width: targetRect.width + pad * 2,
            height: targetRect.height + pad * 2,
            borderRadius: '8px',
            border: '2px solid rgb(99, 102, 241)',
            boxShadow: '0 0 0 4px rgba(99, 102, 241, 0.2)',
            pointerEvents: 'none',
            zIndex: 10001,
          }}
        />
      )}

      {/* Tooltip */}
      <div
        ref={tooltipRef}
        className={`tour-tooltip ${arrowClass}`}
        style={{
          position: 'absolute',
          zIndex: 10002,
          width: 360,
          ...tooltipStyle,
        }}
      >
        <div className="bg-white rounded-lg shadow-xl border border-gray-200 p-5">
          {/* Header */}
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-base font-semibold text-gray-900">{step.title}</h3>
            <button
              onClick={endTour}
              className="text-gray-400 hover:text-gray-600 text-lg leading-none"
              aria-label="Close tour"
            >
              &times;
            </button>
          </div>

          {/* Content */}
          <p className="text-sm text-gray-600 leading-relaxed mb-4">{step.content}</p>

          {/* Footer */}
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-400">
              {currentStep + 1} of {steps.length}
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={endTour}
                className="px-3 py-1.5 text-xs text-gray-500 hover:text-gray-700"
              >
                Skip
              </button>
              {!isFirst && (
                <button
                  onClick={prevStep}
                  className="px-3 py-1.5 text-xs border border-gray-300 rounded-md hover:bg-gray-50"
                >
                  Previous
                </button>
              )}
              <button
                onClick={nextStep}
                className="px-4 py-1.5 text-xs bg-indigo-600 text-white rounded-md hover:bg-indigo-700 font-medium"
              >
                {isLast ? 'Finish' : 'Next'}
              </button>
            </div>
          </div>

          {/* Progress dots */}
          <div className="flex justify-center gap-1.5 mt-3">
            {steps.map((_, idx) => (
              <div
                key={idx}
                className={`w-1.5 h-1.5 rounded-full transition-colors ${
                  idx === currentStep ? 'bg-indigo-600' : idx < currentStep ? 'bg-indigo-300' : 'bg-gray-200'
                }`}
              />
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
