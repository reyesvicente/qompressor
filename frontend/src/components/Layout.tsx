import type { ReactNode } from 'react'
import { Footer } from './Footer'
import { NavBar } from './NavBar'

export function Layout({ children }: { children: ReactNode }) {
  return (
    <>
      <NavBar />
      {children}
      <Footer />
    </>
  )
}
