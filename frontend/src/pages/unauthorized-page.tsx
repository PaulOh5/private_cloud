import { Link } from 'react-router-dom'

import { Button } from '@/shared/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/shared/ui/card'

export function UnauthorizedPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-lg">
        <CardHeader>
          <CardTitle>접근 권한이 없습니다.</CardTitle>
          <CardDescription>현재 계정으로는 요청하신 페이지를 볼 수 없습니다.</CardDescription>
        </CardHeader>
        <CardContent className="flex gap-2">
          <Button asChild>
            <Link to="/instances">인스턴스로 이동</Link>
          </Button>
          <Button asChild variant="outline">
            <Link to="/login">로그인 화면</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
