import { useEffect, useState } from 'react'

import { api } from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

type ApiState = 'checking' | 'ok' | 'unreachable'

export default function App() {
  const [apiState, setApiState] = useState<ApiState>('checking')

  useEffect(() => {
    api
      .GET('/health')
      .then(({ data }) => setApiState(data?.status === 'ok' ? 'ok' : 'unreachable'))
      .catch(() => setApiState('unreachable'))
  }, [])

  return (
    <main className="flex min-h-svh items-center justify-center bg-background p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Thrift Listing Assistant</CardTitle>
          <CardDescription>From an item photo to a priced, published listing.</CardDescription>
        </CardHeader>
        <CardContent className="flex items-center justify-between text-sm">
          <span>API status</span>
          <Badge variant={apiState === 'unreachable' ? 'destructive' : 'secondary'}>
            {apiState}
          </Badge>
        </CardContent>
      </Card>
    </main>
  )
}
