import { createBrowserRouter, Navigate } from 'react-router-dom'

import { RequireAuth } from '@/features/auth/require-auth'
import { RequireRole } from '@/features/auth/require-role'
import { ConsoleLayout } from '@/app/layouts/console-layout'
import { AuditLogDetailPage } from '@/pages/audit-log-detail-page'
import { AuditLogsPage } from '@/pages/audit-logs-page'
import { InstanceDetailPage } from '@/pages/instance-detail-page'
import { InstancesPage } from '@/pages/instances-page'
import { LoginPage } from '@/pages/login-page'
import { NotFoundPage } from '@/pages/not-found-page'
import { TaskDetailPage } from '@/pages/task-detail-page'
import { TasksPage } from '@/pages/tasks-page'
import { TenantDetailPage } from '@/pages/tenant-detail-page'
import { TenantsPage } from '@/pages/tenants-page'
import { UnauthorizedPage } from '@/pages/unauthorized-page'
import { UserDetailPage } from '@/pages/user-detail-page'
import { UsersPage } from '@/pages/users-page'

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/unauthorized',
    element: <UnauthorizedPage />,
  },
  {
    path: '/',
    element: (
      <RequireAuth>
        <ConsoleLayout />
      </RequireAuth>
    ),
    children: [
      {
        index: true,
        element: <Navigate to="/instances" replace />,
      },
      {
        path: 'instances',
        element: <InstancesPage />,
      },
      {
        path: 'instances/:instanceId',
        element: <InstanceDetailPage />,
      },
      {
        path: 'tasks',
        element: <TasksPage />,
      },
      {
        path: 'tasks/:taskId',
        element: <TaskDetailPage />,
      },
      {
        path: 'tenants',
        element: (
          <RequireRole allow={['admin']}>
            <TenantsPage />
          </RequireRole>
        ),
      },
      {
        path: 'tenants/:tenantId',
        element: (
          <RequireRole allow={['admin']}>
            <TenantDetailPage />
          </RequireRole>
        ),
      },
      {
        path: 'users',
        element: (
          <RequireRole allow={['admin']}>
            <UsersPage />
          </RequireRole>
        ),
      },
      {
        path: 'users/:userId',
        element: <UserDetailPage />,
      },
      {
        path: 'audit-logs',
        element: (
          <RequireRole allow={['admin']}>
            <AuditLogsPage />
          </RequireRole>
        ),
      },
      {
        path: 'audit-logs/:logId',
        element: (
          <RequireRole allow={['admin']}>
            <AuditLogDetailPage />
          </RequireRole>
        ),
      },
    ],
  },
  {
    path: '*',
    element: <NotFoundPage />,
  },
])
