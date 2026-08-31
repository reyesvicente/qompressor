import { Coffee } from 'lucide-react'

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="page-container footer-content">
        <p>&copy; {new Date().getFullYear()} Pied Piper. All rights reserved.</p>
        <p className="footer-meta">
          <span>
            A project of{' '}
            <a href="https://vicentereyes.org" target="_blank" rel="noreferrer">
              Vicente G. Reyes
            </a>
          </span>
          <span aria-hidden="true">&middot;</span>
          <span className="footer-credit">
            Built with Django &amp; React <Coffee size={16} className="footer-icon" aria-hidden="true" />
          </span>
        </p>
      </div>
    </footer>
  )
}
