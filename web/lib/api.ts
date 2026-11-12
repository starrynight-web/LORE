export class ApiError extends Error {
  status: number
  body: Record<string, unknown>

  constructor(message: string, status: number, body: Record<string, unknown> = {}) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.body = body
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const text = await response.text();
  let data: T & { error?: string };
  try {
    data = text ? (JSON.parse(text) as T & { error?: string }) : ({} as T & { error?: string });
  } catch {
    throw new ApiError("The setup site could not complete that.", response.status);
  }
  if (!response.ok) {
    throw new ApiError(data.error || "The setup site could not complete that.", response.status, data as Record<string, unknown>);
  }
  return data;
}

export type GovernanceSummary = {
  score: number
  highest_severity: string
  finding_count: number
  freshness: string
  verified_at?: string | null
  accepted_risk: boolean
  skillspector: boolean
  tool: string
}

export type GovernanceFinding = {
  id: string
  category?: string
  severity: string
  title: string
  evidence?: string[]
  description?: string
}

export type Persona = {
  id: string;
  title: string;
  summary: string;
  status: string;
  body: string;
  skill_ids: string[];
  skills?: Skill[];
  governance?: GovernanceSummary;
};

export type Skill = {
  id: string;
  title: string;
  summary: string;
  status: string;
  body: string;
  persona?: string;
  governance?: GovernanceSummary;
};

export type Onboarding = { completed: boolean; step: string }

export type Rank = { id: string; name: string; count: number }

export type Usage = {
  calls: number
  agents: Rank[]
  personas: Rank[]
  skills: Rank[]
  recent: { id: string; time: string; client: string; persona: string; verdict: string; summary: string }[]
}

export type WaitingSkill = { id: string; title: string; summary: string; source: string }

export type RegistrySkill = { name: string; skill_id: string; source: string; installs: number }

export type Codebase = {
  id: string
  name: string
  path: string
  map: { state: string; time?: string; error?: string; links?: { node: string; to: string; relation: string; confidence: string }[] }
}
