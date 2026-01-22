import { Link } from 'react-router-dom'
import { Home, ArrowLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'

export function NotFound() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="text-center space-y-6 max-w-md">
        <div className="space-y-2">
          <h1 className="text-7xl font-bold text-muted-foreground">404</h1>
          <h2 className="text-2xl font-semibold">Page Not Found</h2>
          <p className="text-muted-foreground">
            The page you're looking for doesn't exist or has been moved.
          </p>
        </div>

        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <Button asChild variant="default">
            <Link to="/">
              <Home className="mr-2 h-4 w-4" />
              Go to Dashboard
            </Link>
          </Button>
          <Button asChild variant="outline" onClick={() => window.history.back()}>
            <button type="button">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Go Back
            </button>
          </Button>
        </div>
      </div>
    </div>
  )
}
