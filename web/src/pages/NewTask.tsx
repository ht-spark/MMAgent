import Result from './Result'
import ChatModeling from './ChatModeling'

type TaskStep = 'submit' | 'progress' | 'result'

type Props = {
  task: { step: TaskStep; runId: string | null }
  setTask: (t: { step: TaskStep; runId: string | null }) => void
  onHistory: () => void
}

export default function NewTask({ task, setTask, onHistory }: Props) {
  // 结果页保留原有查看体验
  if (task.step === 'result' && task.runId) {
    return (
      <div className="page page-fill">
        <Result
          runId={task.runId}
          onBack={() => setTask({ step: 'submit', runId: null })}
          onHistory={onHistory}
        />
      </div>
    )
  }

  // 提交 + 进度 两步合并为聊天式界面：
  // - submit：聊天框 + 上传任务/数据，点开始建模
  // - progress：实时把建模进度以聊天消息输出（resumeRunId 接管进行中任务）
  return (
    <div className="page page-fill chat-page">
      <ChatModeling
        resumeRunId={task.step === 'progress' ? task.runId : null}
        onViewResult={(id) => setTask({ step: 'result', runId: id })}
      />
    </div>
  )
}
