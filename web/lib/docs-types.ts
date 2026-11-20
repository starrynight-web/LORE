export interface DocsConfig {
  id: string;
  is_public_accessible: boolean;
  enforce_schedule: boolean;
  schedule_start: string;
  schedule_end: string;
  admin_override: boolean;
  closed_message: string;
  allow_judge_passkey: boolean;
  judge_passkey: string;
  is_currently_open: boolean;
  updated_at: string;
}

export interface DocsPitchSlide {
  number: number;
  id: string;
  title: string;
  subtitle: string;
  badge: string;
  points: string[];
  stats?: Array<{ value: string; label: string }>;
}

export interface DocsPitchDeck {
  title: string;
  tagline: string;
  slides: DocsPitchSlide[];
}

export interface DocsWhitepaper {
  title: string;
  version: string;
  sections: Record<string, any>;
}

export interface DocsTeamMember {
  id: string;
  full_name: string;
  role: string;
  email: string;
  avatar_url: string;
  bio: string;
  skills?: string[];
  github?: string;
  linkedin?: string;
}

export interface DocsTeamData {
  team_name: string;
  charter: string;
  members: DocsTeamMember[];
}

export interface DocsManifestResponse {
  is_open: boolean;
  status: 'active' | 'restricted' | string;
  is_admin?: boolean;
  reason?: 'SCHEDULE_LOCKED' | 'VISIBILITY_OFF' | string;
  message?: string;
  config?: DocsConfig;
  schedule_window?: {
    start: string;
    end: string;
    is_active_now: boolean;
  };
  team?: DocsTeamData;
  pitch_deck?: DocsPitchDeck;
  whitepaper?: DocsWhitepaper;
  live_telemetry?: any;
  system_meta?: {
    app_name: string;
    version: string;
    docs_route: string;
    environment: string;
    license: string;
  };
}
