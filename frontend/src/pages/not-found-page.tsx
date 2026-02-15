import { Link } from 'react-router-dom'

import { Button } from '@/shared/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card'

export function NotFoundPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle>페이지를 찾을 수 없습니다.</CardTitle>
          <CardDescription>요청하신 주소가 존재하지 않거나 이동되었습니다.</CardDescription>
        </CardHeader>
        <CardContent>
          <Button asChild>
            <Link to="/instances">대시보드로 이동</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
