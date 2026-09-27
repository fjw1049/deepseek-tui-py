import { sqliteTable, text, integer, index } from 'drizzle-orm/sqlite-core'
export const shares = sqliteTable('shares', {
  token: text('token').primaryKey(),
  deleteHash: text('delete_hash').notNull(),
  expiresAt: integer('expires_at').notNull(),
}, table => [index('shares_expiry').on(table.expiresAt)])
export const quotas = sqliteTable('quotas', {
  key: text('key').primaryKey(),
  count: integer('count').notNull(),
  expiresAt: integer('expires_at').notNull(),
}, table => [index('quotas_expiry').on(table.expiresAt)])
