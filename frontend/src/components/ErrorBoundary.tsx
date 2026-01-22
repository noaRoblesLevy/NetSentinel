import { Component, ErrorInfo, ReactNode } from 'react'
import { AlertTriangle, RefreshCw, Home } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
  errorInfo: ErrorInfo | null
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    }
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    this.setState({ errorInfo })
    // Log to error reporting service in production
    console.error('ErrorBoundary caught an error:', error, errorInfo)
  }

  handleReload = () => {
    window.location.reload()
  }

  handleGoHome = () => {
    window.location.href = '/'
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null })
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback
      }

      return (
        <div className="min-h-screen flex items-center justify-center bg-background p-4">
          <Card className="w-full max-w-lg">
            <CardHeader className="text-center">
              <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
                <AlertTriangle className="h-6 w-6 text-destructive" />
              </div>
              <CardTitle className="text-xl">Something went wrong</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-center text-muted-foreground">
                An unexpected error occurred. Our team has been notified.
              </p>

              {process.env.NODE_ENV === 'development' && this.state.error && (
                <div className="p-3 bg-muted rounded-lg overflow-auto max-h-40">
                  <p className="text-sm font-mono text-destructive">
                    {this.state.error.toString()}
                  </p>
                  {this.state.errorInfo && (
                    <pre className="text-xs text-muted-foreground mt-2 whitespace-pre-wrap">
                      {this.state.errorInfo.componentStack}
                    </pre>
                  )}
                </div>
              )}

              <div className="flex flex-col sm:flex-row gap-3 justify-center">
                <Button onClick={this.handleReset} variant="default">
                  <RefreshCw className="mr-2 h-4 w-4" />
                  Try Again
                </Button>
                <Button onClick={this.handleGoHome} variant="outline">
                  <Home className="mr-2 h-4 w-4" />
                  Go to Dashboard
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )
    }

    return this.props.children
  }
}
