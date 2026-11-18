export type RegistrationStatus = "pending_approval" | "approved" | "rejected"

export type RegistrationRecord = {
  id: string
  name: string
  email: string
  repoUrl?: string
  status: RegistrationStatus
  schema_version: number
}

export type ServiceResult<T> =
  | { ok: true; data: T }
  | { ok: false; error_code: string; message?: string }

export type ReadinessInput = {
  projectIdea: boolean
  laptopCharger: boolean
  githubRepo: boolean
  workflowPlan: boolean
  agentQuestions: boolean
}

export type DelegationCard = {
  title: string
  targetPath: string
}
