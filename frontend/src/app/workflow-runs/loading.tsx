import { LoadingState } from './components/ListStates'

export default function WorkflowRunsLoading() {
  return (
    <div className="page-shell">
      <main className="page-frame">
        <div className="page-container">
          <LoadingState />
        </div>
      </main>
    </div>
  )
}
