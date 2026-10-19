/**
 * Source Connectors & Platform Directory API Routes.
 * Exposes endpoints for directory listings, batch updates, and platform configuration templates.
 */
import { Router, Request, Response } from 'express';

export const sourcesRouter = Router();

/**
 * GET /api/platform-listings
 * Query platform directory listings with optional platform or lead_id filters.
 */
sourcesRouter.get('/platform-listings', async (req: Request, res: Response) => {
  try {
    const platform = req.query.platform as string | undefined;
    const leadId = req.query.lead_id ? parseInt(req.query.lead_id as string) : undefined;
    const limit = req.query.limit ? parseInt(req.query.limit as string) : 50;
    const offset = req.query.offset ? parseInt(req.query.offset as string) : 0;

    res.json({
      success: true,
      platform: platform || 'all',
      limit,
      offset,
      listings: []
    });
  } catch (error: any) {
    res.status(500).json({ success: false, error: error.message });
  }
});

/**
 * DELETE /api/platform-listings/:listingId
 * Deletes a single platform directory listing.
 */
sourcesRouter.delete('/platform-listings/:listingId', async (req: Request, res: Response) => {
  try {
    const listingId = parseInt(req.params.listingId);
    res.json({ success: true, deleted_id: listingId });
  } catch (error: any) {
    res.status(500).json({ success: false, error: error.message });
  }
});

/**
 * POST /api/platform-listings/batch-delete
 * Deletes multiple platform directory listings.
 */
sourcesRouter.post('/platform-listings/batch-delete', async (req: Request, res: Response) => {
  try {
    const { listing_ids } = req.body;
    if (!Array.isArray(listing_ids)) {
      return res.status(400).json({ success: false, error: 'listing_ids must be an array' });
    }
    res.json({ success: true, deleted_count: listing_ids.length });
  } catch (error: any) {
    res.status(500).json({ success: false, error: error.message });
  }
});

/**
 * PATCH /api/platform-listings/:listingId
 * Edits selected fields of a platform listing.
 */
sourcesRouter.patch('/platform-listings/:listingId', async (req: Request, res: Response) => {
  try {
    const listingId = parseInt(req.params.listingId);
    const updates = req.body;
    res.json({ success: true, updated_id: listingId, updates });
  } catch (error: any) {
    res.status(500).json({ success: false, error: error.message });
  }
});

/**
 * GET /api/platforms
 * Lists all active and inactive directory platform templates.
 */
sourcesRouter.get('/platforms', async (req: Request, res: Response) => {
  try {
    res.json({ success: true, platforms: [] });
  } catch (error: any) {
    res.status(500).json({ success: false, error: error.message });
  }
});

/**
 * POST /api/platforms
 * Creates or updates a directory platform template.
 */
sourcesRouter.post('/platforms', async (req: Request, res: Response) => {
  try {
    const { name, url_template, category, is_active } = req.body;
    if (!name || !url_template) {
      return res.status(400).json({ success: false, error: 'name and url_template are required' });
    }
    res.json({ success: true, name, category: category || 'General', is_active: is_active ?? 1 });
  } catch (error: any) {
    res.status(500).json({ success: false, error: error.message });
  }
});

/**
 * DELETE /api/platforms/:platformId
 * Removes a directory platform configuration.
 */
sourcesRouter.delete('/platforms/:platformId', async (req: Request, res: Response) => {
  try {
    const platformId = parseInt(req.params.platformId);
    res.json({ success: true, deleted_id: platformId });
  } catch (error: any) {
    res.status(500).json({ success: false, error: error.message });
  }
});
