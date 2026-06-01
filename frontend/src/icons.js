import { h } from 'vue'

const paths = {
  ArrowLeft: [h('path', { d: 'M19 12H5' }), h('path', { d: 'M12 19l-7-7 7-7' })],
  ArrowRight: [h('path', { d: 'M5 12h14' }), h('path', { d: 'M12 5l7 7-7 7' })],
  Bell: [h('path', { d: 'M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9' }), h('path', { d: 'M13.7 21a2 2 0 0 1-3.4 0' })],
  Boxes: [h('path', { d: 'M3 7l9-4 9 4-9 4-9-4z' }), h('path', { d: 'M3 7v10l9 4 9-4V7' }), h('path', { d: 'M12 11v10' })],
  Brain: [h('path', { d: 'M9 3a3 3 0 0 0-3 3v1a3 3 0 0 0-2 5 3 3 0 0 0 2 5v1a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z' }), h('path', { d: 'M15 3a3 3 0 0 1 3 3v1a3 3 0 0 1 2 5 3 3 0 0 1-2 5v1a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z' })],
  Check: [h('path', { d: 'M20 6L9 17l-5-5' })],
  CheckCircle2: [h('circle', { cx: 12, cy: 12, r: 10 }), h('path', { d: 'M9 12l2 2 4-4' })],
  Circle: [h('circle', { cx: 12, cy: 12, r: 10 })],
  ClipboardList: [h('rect', { x: 8, y: 2, width: 8, height: 4, rx: 1 }), h('path', { d: 'M9 5H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-4' }), h('path', { d: 'M9 12h6M9 16h6' })],
  Compass: [h('circle', { cx: 12, cy: 12, r: 10 }), h('path', { d: 'M16 8l-2 6-6 2 2-6 6-2z' })],
  CopyPlus: [h('rect', { x: 8, y: 8, width: 11, height: 11, rx: 2 }), h('path', { d: 'M5 15V5h10' }), h('path', { d: 'M13.5 11.5v4M11.5 13.5h4' })],
  FilePlus2: [h('path', { d: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z' }), h('path', { d: 'M14 2v6h6' }), h('path', { d: 'M12 18v-6M9 15h6' })],
  FileText: [h('path', { d: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z' }), h('path', { d: 'M14 2v6h6' }), h('path', { d: 'M8 13h8M8 17h8M8 9h2' })],
  GitFork: [h('circle', { cx: 6, cy: 3, r: 3 }), h('circle', { cx: 18, cy: 3, r: 3 }), h('circle', { cx: 12, cy: 21, r: 3 }), h('path', { d: 'M6 6v3a6 6 0 0 0 6 6 6 6 0 0 0 6-6V6' })],
  Inbox: [h('path', { d: 'M22 12h-6l-2 3h-4l-2-3H2' }), h('path', { d: 'M5.5 5h13L22 12v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6l3.5-7z' })],
  LoaderCircle: [h('path', { d: 'M21 12a9 9 0 1 1-6.2-8.56' })],
  LogOut: [h('path', { d: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4' }), h('path', { d: 'M16 17l5-5-5-5' }), h('path', { d: 'M21 12H9' })],
  MessageSquare: [h('path', { d: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z' })],
  Play: [h('path', { d: 'M5 3l14 9-14 9V3z' })],
  PlusCircle: [h('circle', { cx: 12, cy: 12, r: 10 }), h('path', { d: 'M12 8v8M8 12h8' })],
  RefreshCw: [h('path', { d: 'M21 12a9 9 0 0 1-15 6.7L3 16' }), h('path', { d: 'M3 21v-5h5' }), h('path', { d: 'M3 12a9 9 0 0 1 15-6.7L21 8' }), h('path', { d: 'M21 3v5h-5' })],
  Save: [h('path', { d: 'M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z' }), h('path', { d: 'M17 21v-8H7v8' }), h('path', { d: 'M7 3v5h8' })],
  Search: [h('circle', { cx: 11, cy: 11, r: 8 }), h('path', { d: 'M21 21l-4.3-4.3' })],
  Send: [h('path', { d: 'M22 2L11 13' }), h('path', { d: 'M22 2l-7 20-4-9-9-4 20-7z' })],
  Settings2: [h('path', { d: 'M20 7h-9' }), h('path', { d: 'M14 17H5' }), h('circle', { cx: 17, cy: 17, r: 3 }), h('circle', { cx: 7, cy: 7, r: 3 })],
  Shield: [h('path', { d: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z' }), h('path', { d: 'M9 12l2 2 4-4' })],
  Trash2: [h('path', { d: 'M3 6h18' }), h('path', { d: 'M8 6V4h8v2' }), h('path', { d: 'M19 6l-1 14H6L5 6' }), h('path', { d: 'M10 11v6M14 11v6' })],
  UploadCloud: [h('path', { d: 'M16 16l-4-4-4 4' }), h('path', { d: 'M12 12v9' }), h('path', { d: 'M20.4 16.4A5 5 0 0 0 18 7h-1.3A8 8 0 1 0 4 15.3' })],
  UserRound: [h('circle', { cx: 12, cy: 8, r: 5 }), h('path', { d: 'M20 21a8 8 0 0 0-16 0' })],
  Users: [h('path', { d: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2' }), h('circle', { cx: 9, cy: 7, r: 4 }), h('path', { d: 'M22 21v-2a4 4 0 0 0-3-3.9' }), h('path', { d: 'M16 3.1a4 4 0 0 1 0 7.8' })],
  Workflow: [h('rect', { x: 3, y: 4, width: 6, height: 5, rx: 1 }), h('rect', { x: 15, y: 4, width: 6, height: 5, rx: 1 }), h('rect', { x: 9, y: 15, width: 6, height: 5, rx: 1 }), h('path', { d: 'M9 6.5h6M12 9v6' })],
  X: [h('path', { d: 'M18 6L6 18' }), h('path', { d: 'M6 6l12 12' })],
  XCircle: [h('circle', { cx: 12, cy: 12, r: 10 }), h('path', { d: 'M15 9l-6 6M9 9l6 6' })],
}

function createIcon(label) {
  return {
    name: `${label}Icon`,
    props: {
      size: { type: [Number, String], default: 20 },
      color: { type: String, default: 'currentColor' },
      strokeWidth: { type: [Number, String], default: 2 },
    },
    setup(props) {
      return () => h(
        'svg',
        {
          xmlns: 'http://www.w3.org/2000/svg',
          width: props.size,
          height: props.size,
          viewBox: '0 0 24 24',
          fill: 'none',
          stroke: props.color,
          'stroke-width': props.strokeWidth,
          'stroke-linecap': 'round',
          'stroke-linejoin': 'round',
          'aria-hidden': 'true',
        },
        paths[label],
      )
    },
  }
}

export const ArrowLeft = createIcon('ArrowLeft')
export const ArrowRight = createIcon('ArrowRight')
export const Bell = createIcon('Bell')
export const Boxes = createIcon('Boxes')
export const Brain = createIcon('Brain')
export const Check = createIcon('Check')
export const CheckCircle2 = createIcon('CheckCircle2')
export const Circle = createIcon('Circle')
export const ClipboardList = createIcon('ClipboardList')
export const Compass = createIcon('Compass')
export const CopyPlus = createIcon('CopyPlus')
export const FilePlus2 = createIcon('FilePlus2')
export const FileText = createIcon('FileText')
export const GitFork = createIcon('GitFork')
export const Inbox = createIcon('Inbox')
export const LoaderCircle = createIcon('LoaderCircle')
export const LogOut = createIcon('LogOut')
export const MessageSquare = createIcon('MessageSquare')
export const Play = createIcon('Play')
export const PlusCircle = createIcon('PlusCircle')
export const RefreshCw = createIcon('RefreshCw')
export const Save = createIcon('Save')
export const Search = createIcon('Search')
export const Send = createIcon('Send')
export const Settings2 = createIcon('Settings2')
export const Shield = createIcon('Shield')
export const Trash2 = createIcon('Trash2')
export const UploadCloud = createIcon('UploadCloud')
export const UserRound = createIcon('UserRound')
export const Users = createIcon('Users')
export const Workflow = createIcon('Workflow')
export const X = createIcon('X')
export const XCircle = createIcon('XCircle')
