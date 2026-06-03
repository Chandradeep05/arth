'use client';

import React, { Component, type ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface ErrorBoundaryProps {
  children: ReactNode;
  fallbackTitle?: string;
  moduleName?: string;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    if (process.env.NODE_ENV === 'development') {
      console.error('[ErrorBoundary]', error, info.componentStack);
    }
  }

  handleReset = (): void => {
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center gap-4 p-8 rounded-lg border border-[var(--border)] bg-[var(--surface)]">
          <div className="flex items-center gap-3 text-[var(--accent-orange)]">
            <AlertTriangle className="h-6 w-6" />
            <h3 className="font-heading text-lg font-bold">
              {this.props.fallbackTitle ?? 'Something went wrong'}
            </h3>
          </div>

          <p className="text-sm text-[var(--text-muted)] text-center max-w-md">
            {this.props.moduleName
              ? `The ${this.props.moduleName} module encountered an error. Other modules are unaffected.`
              : 'This module encountered an error. Other modules are unaffected.'}
          </p>

          {process.env.NODE_ENV === 'development' && this.state.error && (
            <pre className="mt-2 max-w-lg overflow-auto rounded border border-[var(--border)] bg-[var(--bg)] p-3 text-xs text-[var(--red)] font-mono">
              {this.state.error.message}
            </pre>
          )}

          <button
            onClick={this.handleReset}
            className="
              inline-flex items-center gap-2 px-4 py-2 rounded
              text-sm font-medium
              border border-[var(--border-bright)]
              bg-[var(--surface-2)] text-[var(--text)]
              hover:bg-[var(--border)] hover:border-[var(--accent)]
              transition-colors duration-200
              cursor-pointer
            "
          >
            <RefreshCw className="h-4 w-4" />
            Retry
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
