import React from 'react'
import ReactDOM from 'react-dom/client'
import { RouterProvider, createBrowserRouter, Navigate } from 'react-router-dom'

import './index.css'
import Layout from './Layout'
import Dashboard from './pages/Dashboard'
import RunDetail from './pages/RunDetail'
import Approvals from './pages/Approvals'
import Policies from './pages/Policies'
import Spend from './pages/Spend'

const router = createBrowserRouter(
  [
    {
      path: '/',
      element: <Layout />,
      children: [
        { index: true, element: <Dashboard /> },
        { path: 'runs/:runId', element: <RunDetail /> },
        { path: 'approvals', element: <Approvals /> },
        { path: 'policies', element: <Policies /> },
        { path: 'spend', element: <Spend /> },
        { path: '*', element: <Navigate to="/" replace /> },
      ],
    },
  ],
  { basename: import.meta.env.BASE_URL.replace(/\/$/, '') || '/' },
)

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
)
