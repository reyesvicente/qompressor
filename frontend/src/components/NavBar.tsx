import { Button, Navbar, NavbarActions, NavbarBrand, NavbarContainer, NavbarLink } from 'ice-ds'
import type { MouseEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export function NavBar() {
  const { isAuthenticated, logout } = useAuth()
  const navigate = useNavigate()

  function goTo(path: string) {
    return (event: MouseEvent) => {
      event.preventDefault()
      navigate(path)
    }
  }

  function handleSignOut() {
    logout()
    navigate('/')
  }

  return (
    <Navbar sticky>
      <NavbarContainer className="page-container">
        <NavbarBrand href="/" onClick={goTo('/')}>
          Pied Piper
        </NavbarBrand>
        <NavbarActions>
          {isAuthenticated ? (
            <>
              <NavbarLink href="/dashboard" onClick={goTo('/dashboard')}>
                Dashboard
              </NavbarLink>
              <Button size="sm" variant="secondary" onClick={handleSignOut}>
                Sign out
              </Button>
            </>
          ) : (
            <>
              <NavbarLink href="/login" onClick={goTo('/login')}>
                Log in
              </NavbarLink>
              <Button size="sm" onClick={() => navigate('/signup')}>
                Sign up
              </Button>
            </>
          )}
        </NavbarActions>
      </NavbarContainer>
    </Navbar>
  )
}
