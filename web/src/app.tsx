import {useEffect, useState} from 'react';

import {GROUNDED_ANSWER, SOURCES} from './fixtures/sample-data';
import {useTheme} from './lib/theme';
import {AskScreen} from './screens/ask/ask-screen';
import {BOARDS, Gallery, type BoardId} from './screens/design-system/gallery';

function useHash() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const update = () => setHash(window.location.hash);
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  return hash;
}

function boardFrom(hash: string): BoardId | undefined {
  const match = /^#\/design(?:\/([\w-]+))?$/.exec(hash);
  if (!match) return undefined;
  return BOARDS.find(b => b.id === match[1])?.id ?? 'overview';
}

/**
 * Routes: `#/design/<board>` shows the Assay design-system pages; anything
 * else shows Ask, which renders sample content until the API exists.
 */
export function App() {
  const hash = useHash();
  const [theme, setTheme] = useTheme();
  const board = boardFrom(hash);

  if (board) {
    return <Gallery board={board} theme={theme} onThemeChange={setTheme} />;
  }
  return (
    <AskScreen
      answer={GROUNDED_ANSWER}
      sources={SOURCES}
      scope={['Policies', 'Standards', 'Minutes']}
      followUps={[
        'Which record classes are in Schedule B?',
        'How does a legal hold change this?',
      ]}
      deployment="compact · air-gapped"
      pendingReviews={4}
    />
  );
}
