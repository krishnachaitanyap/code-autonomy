'use client';

import { createContext, useCallback, useContext, useEffect, useState } from 'react';

export interface TourStep {
  target: string;       // CSS selector (e.g. '[data-tour="welcome"]')
  title: string;
  content: string;
  placement?: 'top' | 'bottom' | 'left' | 'right';
}

interface TourContextValue {
  isActive: boolean;
  currentStep: number;
  steps: TourStep[];
  startTour: (steps: TourStep[]) => void;
  nextStep: () => void;
  prevStep: () => void;
  endTour: () => void;
  hasSeenTour: boolean;
}

const TourContext = createContext<TourContextValue>({
  isActive: false,
  currentStep: 0,
  steps: [],
  startTour: () => {},
  nextStep: () => {},
  prevStep: () => {},
  endTour: () => {},
  hasSeenTour: false,
});

const STORAGE_KEY = 'ca-tour-seen';

export function TourProvider({ children }: { children: React.ReactNode }) {
  const [isActive, setIsActive] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [steps, setSteps] = useState<TourStep[]>([]);
  const [hasSeenTour, setHasSeenTour] = useState(true); // default true to avoid flash

  useEffect(() => {
    setHasSeenTour(localStorage.getItem(STORAGE_KEY) === 'true');
  }, []);

  const startTour = useCallback((tourSteps: TourStep[]) => {
    setSteps(tourSteps);
    setCurrentStep(0);
    setIsActive(true);
  }, []);

  const nextStep = useCallback(() => {
    setCurrentStep((prev) => {
      if (prev >= steps.length - 1) {
        setIsActive(false);
        localStorage.setItem(STORAGE_KEY, 'true');
        setHasSeenTour(true);
        return 0;
      }
      return prev + 1;
    });
  }, [steps.length]);

  const prevStep = useCallback(() => {
    setCurrentStep((prev) => Math.max(0, prev - 1));
  }, []);

  const endTour = useCallback(() => {
    setIsActive(false);
    setCurrentStep(0);
    localStorage.setItem(STORAGE_KEY, 'true');
    setHasSeenTour(true);
  }, []);

  return (
    <TourContext.Provider
      value={{ isActive, currentStep, steps, startTour, nextStep, prevStep, endTour, hasSeenTour }}
    >
      {children}
    </TourContext.Provider>
  );
}

export function useTour() {
  return useContext(TourContext);
}
