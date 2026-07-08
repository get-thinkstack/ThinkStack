import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, LabelList } from 'recharts';
import useThemeColors from './useThemeColors';
import ChartCard from './ChartCard';

const shortName = (fn) => {
  const base = (fn || '').replace(/\.pdf$/i, '');
  return base.length > 18 ? base.slice(0, 17) + '…' : base;
};

/** horizontal bar chart of knowledge chunks per ingested paper. */
export default function LibraryChart({ documents = [] }) {
  const c = useThemeColors();
  const data = documents
    .map((d) => ({ name: shortName(d.filename), full: d.filename, chunks: d.chunks || 0 }))
    .filter((d) => d.chunks > 0);

  if (data.length === 0) return null;

  return (
    <ChartCard title="Knowledge base — chunks per paper" height={Math.max(190, data.length * 56)} style={{ marginBottom: '2rem' }}>
      <ResponsiveContainer>
        <BarChart data={data} layout="vertical" margin={{ left: 6, right: 40, top: 6, bottom: 6 }} barCategoryGap="28%">
          <XAxis type="number" hide />
          <YAxis
            type="category"
            dataKey="name"
            width={150}
            tick={{ fill: c['text-2'], fontSize: 12 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            cursor={{ fill: c['accent-soft'] }}
            contentStyle={{ background: c.surface, border: `1px solid ${c.border}`, borderRadius: 12, color: c.text }}
            labelFormatter={(l, p) => p?.[0]?.payload?.full || l}
            formatter={(v) => [`${v} chunks`, '']}
          />
          <Bar dataKey="chunks" radius={[6, 6, 6, 6]} barSize={22} isAnimationActive animationDuration={650}>
            {data.map((_, i) => (
              <Cell key={i} fill={i % 2 ? c['accent-2'] : c.accent} />
            ))}
            <LabelList dataKey="chunks" position="right" fill={c['text-2']} fontSize={11} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}
