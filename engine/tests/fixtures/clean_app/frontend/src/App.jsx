import { useState } from 'react'

export default function App() {
  const [email, setEmail] = useState('')
  sessionStorage.setItem('theme', 'dark')
  return (
    <form>
      <input id="email" name="email" value={email} onChange={(e) => setEmail(e.target.value)} />
    </form>
  )
}
