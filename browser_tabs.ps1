# Read the browser tabs of Edge / Chrome / Brave.
#
# Two modes, because UI Automation can only read the address bar of the ACTIVE tab:
#   -Mode titles            list windows + tab titles only. No tab is switched (fast, no flicker).
#   -Mode url -Win <pid> -Index <n>
#                           switch to that one tab, read its URL, then switch back.
#
# Output: JSON on stdout.
# Note: keep this file pure ASCII. Windows PowerShell 5.1 reads .ps1 without a
# BOM as ANSI, so CJK literals are expressed with \uXXXX escapes below.

param(
  [string]$Mode = 'titles',
  [int]$Win = 0,
  [int]$Index = -1
)

$ErrorActionPreference = 'Continue'
try {
  Add-Type -AssemblyName UIAutomationClient
  Add-Type -AssemblyName UIAutomationTypes
} catch {
  Write-Output '[]'
  exit 0
}
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$statusPattern = '\s*-\s*(\u7761\u7720|\u5df2\u4e22\u5f03|\u4f11\u7720|\u51bb\u7ed3|\u6d3b\u52a8|\u5185\u5b58\u4f7f\u7528\u7387)(\s*-\s*[^-]+)?$'

function Clean-Title([string]$name) {
  if (-not $name) { return '' }
  for ($i = 0; $i -lt 4; $i++) {
    $next = [regex]::Replace($name, $statusPattern, '')
    if ($next -eq $name) { break }
    $name = $next
  }
  return $name.Trim()
}

# Convert to pure ASCII (\uXXXX) so output survives any stdout encoding.
function To-AsciiJson([string]$text) {
  $sb = New-Object System.Text.StringBuilder
  foreach ($ch in $text.ToCharArray()) {
    $code = [int][char]$ch
    if ($code -lt 128) { [void]$sb.Append($ch) }
    else { [void]$sb.Append(('\u{0:x4}' -f $code)) }
  }
  return $sb.ToString()
}

function Emit([string]$json) { Write-Output (To-AsciiJson $json) }

$browsers = @('msedge', 'chrome', 'brave', 'chromium', '360se', '360chrome', 'opera', 'vivaldi')

$root = [System.Windows.Automation.AutomationElement]::RootElement
$children = $root.FindAll([System.Windows.Automation.TreeScope]::Children,
                          [System.Windows.Automation.Condition]::TrueCondition)

$tabCond = New-Object System.Windows.Automation.PropertyCondition(
  [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
  [System.Windows.Automation.ControlType]::TabItem)

# ---------------------------------------------------------------- titles mode
if ($Mode -eq 'titles') {
  $list = New-Object System.Collections.ArrayList
  foreach ($w in $children) {
    if ($w.Current.ClassName -ne 'Chrome_WidgetWin_1') { continue }
    $procId = $w.Current.ProcessId
    $procName = ''
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($proc) { $procName = $proc.ProcessName.ToLower() }
    if ($browsers -notcontains $procName) { continue }

    $tabs = @($w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $tabCond))
    if ($tabs.Count -eq 0) { continue }

    for ($i = 0; $i -lt $tabs.Count; $i++) {
      $title = Clean-Title ([string]$tabs[$i].Current.Name)
      [void]$list.Add([pscustomobject]@{ win = $procId; index = $i; title = $title; browser = $procName })
    }
  }
  if ($list.Count -eq 0) { Emit '[]' }
  else {
    $json = ConvertTo-Json -InputObject @($list) -Compress -Depth 4
    if ($list.Count -eq 1) { $json = '[' + $json + ']' }
    Emit $json
  }
  exit 0
}

# ------------------------------------------------------------------- url mode
# Switch to one specified tab, read the address bar, then restore the previous tab.
$target = $null
foreach ($w in $children) {
  if ($w.Current.ClassName -ne 'Chrome_WidgetWin_1') { continue }
  if ($w.Current.ProcessId -ne $Win) { continue }
  $target = $w
  break
}
if (-not $target) { Emit '{"url":""}'; exit 0 }

$tabs = @($target.FindAll([System.Windows.Automation.TreeScope]::Descendants, $tabCond))
if ($tabs.Count -eq 0 -or $Index -lt 0 -or $Index -ge $tabs.Count) { Emit '{"url":""}'; exit 0 }

$addr = $null
foreach ($aid in @('view_1017', 'view_1013', 'view_1001')) {
  $addr = $target.FindFirst([System.Windows.Automation.TreeScope]::Descendants,
    (New-Object System.Windows.Automation.PropertyCondition(
      [System.Windows.Automation.AutomationElement]::AutomationIdProperty, $aid)))
  if ($addr) { break }
}
if (-not $addr) { Emit '{"url":""}'; exit 0 }

$vp = $null
try { $vp = $addr.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern) } catch { $vp = $null }
if (-not $vp) { Emit '{"url":""}'; exit 0 }

$original = $null
foreach ($t in $tabs) {
  $isSel = $false
  try { $isSel = $t.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Current.IsSelected } catch { $isSel = $false }
  if ($isSel) { $original = $t; break }
}

$url = ''
try {
  $tabs[$Index].GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
  Start-Sleep -Milliseconds 260
  $url = [string]$vp.Current.Value
} catch { $url = '' }

if ($original) {
  try { $original.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select() } catch {}
}

if (-not $url) { Emit '{"url":""}' }
else {
  $obj = [pscustomobject]@{ url = $url }
  Emit (ConvertTo-Json -InputObject $obj -Compress)
}
