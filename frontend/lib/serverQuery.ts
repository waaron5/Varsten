import "server-only";

import { QueryClient, dehydrate } from "@tanstack/react-query";

type QuerySpec = {
  key: readonly unknown[];
  load: (token: string, projectId: string | undefined) => Promise<unknown>;
};

// Prefetches a page's reads on the server into a throwaway QueryClient and
// returns the dehydrated cache. The page wraps its client tree in a
// <HydrationBoundary state={...}> so those queries resolve from cache on the
// first client render (and in the server-rendered HTML), keyed identically to
// useProjectResource: ["projectResource", projectId, ...key]. prefetchQuery does
// not throw, so a read that fails server-side is simply absent and the client
// refetches it normally.
export async function prefetchProjectQueries(
  token: string,
  projectId: string,
  specs: QuerySpec[],
) {
  const queryClient = new QueryClient();
  await Promise.all(
    specs.map((spec) =>
      queryClient.prefetchQuery({
        queryKey: ["projectResource", projectId, ...spec.key],
        queryFn: () => spec.load(token, projectId),
      }),
    ),
  );
  return dehydrate(queryClient);
}
