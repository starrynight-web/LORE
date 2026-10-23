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
};
