import { STSEvent } from './store/dashboardStore'

// The project's own vocabulary: categories describe AIS evidence, not intent.
export const STATUS: Record<STSEvent['status'], { label: string; color: string; meaning: string }> = {
  AIS_VISIBLE: {
    label: 'AIS visible',
    color: '#1C93CF',
    meaning: 'Both partners were broadcasting AIS when the image was taken.',
  },
  AIS_PARTIAL: {
    label: 'AIS partial',
    color: '#C77D06',
    meaning: 'One identity matched. The other was silent, or timing, coverage or matching fell short.',
  },
  AIS_UNMATCHED: {
    label: 'AIS unmatched',
    color: '#F0306F',
    meaning: 'No AIS identity matched either hull. A candidate for review, not a finding of concealment.',
  },
}

export const STATUS_ORDER = Object.keys(STATUS) as STSEvent['status'][]
