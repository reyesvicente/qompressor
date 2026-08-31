import { Card, CardDescription, CardTitle, buttonVariants } from 'ice-ds'
import { Link } from 'react-router-dom'
import { Layout } from '../components/Layout'

const FEATURES: Array<{
  title: string
  body: string
  variant: 'default' | 'info' | 'success' | 'premium'
}> = [
  {
    title: 'Content-aware chunking',
    body: 'Objects are split on content-defined boundaries, not fixed offsets, so a single byte inserted upstream does not invalidate every chunk downstream.',
    variant: 'default',
  },
  {
    title: 'Global deduplication',
    body: 'Identical chunks are stored once, ever, across every object and every tenant. Refcounts make cleanup safe without locking the hot path.',
    variant: 'info',
  },
  {
    title: 'Trained dictionaries',
    body: 'Per-corpus dictionaries are trained on real samples, so small, repetitive records compress far better than generic codecs manage alone.',
    variant: 'premium',
  },
  {
    title: 'A policy per workload',
    body: 'Fast, balanced, or archival: pick the point on the ratio-versus-time curve that fits the object, not one setting for everything.',
    variant: 'success',
  },
]

export function LandingPage() {
  return (
    <Layout>
      <header className="hero-section page-container">
        <p className="eyebrow">Middle-out compression, minus the pitch deck</p>
        <h1>Store less. Restore everything.</h1>
        <p className="hero-sub">
          Pied Piper is a content-aware, deduplicating compression engine. Upload once,
          and every duplicate chunk across your entire corpus is stored exactly one
          time — with a byte-for-byte reconstruction guarantee.
        </p>
        <Link to="/signup" className={buttonVariants({ variant: 'primary', size: 'lg' })}>
          Get started
        </Link>
      </header>

      <section className="feature-grid page-container">
        {FEATURES.map((feature) => (
          <Card key={feature.title} variant={feature.variant} elevation="md">
            <CardTitle>{feature.title}</CardTitle>
            <CardDescription>{feature.body}</CardDescription>
          </Card>
        ))}
      </section>

      <section className="score-section page-container">
        <Card variant="inverse" elevation="lg">
          <CardTitle>Ranked the only way that matters</CardTitle>
          <CardDescription>
            Every codec run is scored against a Weissman-style baseline — ratio traded
            against log-time, on the same corpus, on the same box — so a better number
            means a better tradeoff, not a week of extra CPU for another two percent.
          </CardDescription>
        </Card>
      </section>
    </Layout>
  )
}
