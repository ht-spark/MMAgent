import Submit from './Submit'
import Progress from './Progress'
import Result from './Result'

type TaskStep = 'submit' | 'progress' | 'result'

type Props = {
  task: { step: TaskStep; runId: string | null }
  setTask: (t: { step: TaskStep; runId: string | null }) => void
  onHistory: () => void
}

const STEPS = ['数据上传', '执行求解', '输出结果']

export default function NewTask({ task, setTask, onHistory }: Props) {
  const idx = task.step === 'submit' ? 0 : task.step === 'progress' ? 1 : 2

  return (
    <div className="page page-fill">
      <div className="stepper">
        {STEPS.map((label, i) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', flex: i < 2 ? 1 : 'auto' }}>
            <div className={`step ${i === idx ? 'active' : ''} ${i < idx ? 'done' : ''}`}>
              <span className="step-num">{i < idx ? '✓' : i + 1}</span>
              <span className="step-label">{label}</span>
            </div>
            {i < 2 && <span className="step-line" />}
          </div>
        ))}
      </div>

      {task.step === 'submit' && (
        <Submit onSubmitted={(id) => setTask({ step: 'progress', runId: id })} />
      )}

      {task.step === 'progress' && task.runId && (
        <Progress
          runId={task.runId}
          onDone={() => setTask((s) => ({ ...s, step: 'result' }))}
        />
      )}

      {task.step === 'result' && task.runId && (
        <Result
          runId={task.runId}
          onBack={() => setTask({ step: 'submit', runId: null })}
          onHistory={onHistory}
        />
      )}
    </div>
  )
}
