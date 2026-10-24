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
    throw new Error("The setup site could not complete that.");
  }
  if (!response.ok) {
    throw new Error(data.error || "The setup site could not complete that.");
  }
  return data;
}

export type Persona = {
  id: string;
  title: string;
  summary: string;
  status: string;
  body: string;
  skill_ids: string[];
  skills?: Skill[];
};

export type Skill = {
  id: string;
  title: string;
  summary: string;
  status: string;
  body: string;
  persona?: string;
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
