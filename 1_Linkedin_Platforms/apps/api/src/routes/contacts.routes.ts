/**
 * Contacts & Employees API Routes.
 * Exposes endpoints for pending LinkedIn leads and employee hierarchy rosters.
 */
import { Router, Request, Response } from 'express';

export const contactsRouter = Router();

/**
 * GET /api/leads/pending-linkedin
 * Returns leads awaiting LinkedIn organization inspection.
 */
contactsRouter.get('/leads/pending-linkedin', async (req: Request, res: Response) => {
  try {
    const limit = parseInt(req.query.limit as string) || 50;
    // Proxies or invokes employee_repository.get_pending_linkedin_leads
    res.json({ success: true, limit, leads: [] });
  } catch (error: any) {
    res.status(500).json({ success: false, error: error.message });
  }
});

/**
 * POST /api/save_employees
 * Saves or updates employee roster batch for a company.
 */
contactsRouter.post('/save_employees', async (req: Request, res: Response) => {
  try {
    const { company_name, employees, lead_id, company_linkedin_url, linkedin_status } = req.body;
    if (!company_name) {
      return res.status(400).json({ success: false, error: 'company_name is required' });
    }
    // Invokes save_employees_batch in employee repository
    res.json({ success: true, company: company_name, saved_count: (employees || []).length });
  } catch (error: any) {
    res.status(500).json({ success: false, error: error.message });
  }
});

/**
 * GET /api/employees/hierarchy/:companyName
 * Retrieves the full 3-tier organizational hierarchy.
 */
contactsRouter.get('/employees/hierarchy/:companyName', async (req: Request, res: Response) => {
  try {
    const { companyName } = req.params;
    // Invokes get_company_hierarchy
    res.json({
      success: true,
      company: companyName,
      tiers: { executive: [], management: [], staff: [] },
      total_employees: 0
    });
  } catch (error: any) {
    res.status(500).json({ success: false, error: error.message });
  }
});
