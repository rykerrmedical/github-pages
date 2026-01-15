const puppeteer = require('puppeteer');
const nodemailer = require('nodemailer');

async function approveEdAppUsers() {
  const results = {
    approved: [],
    errors: [],
    timestamp: new Date().toISOString()
  };

  let browser;
  
  try {
    console.log('Launching browser...');
    browser = await puppeteer.launch({
      headless: 'new',
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });

    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 800 });

    // Login to EdApp
    console.log('Navigating to login page...');
    await page.goto('https://admin.edapp.com/login', { waitUntil: 'networkidle2' });
    
    // Wait for email input and fill it
    await page.waitForSelector('input[name="nameOrEmail"]', { timeout: 10000 });
    await page.type('input[name="nameOrEmail"]', process.env.EDAPP_EMAIL);
    
    // Find and fill password
    await page.type('input[name="password"]', process.env.EDAPP_PASSWORD);
    
    // Click login button
    await page.click('button#btn-login');
    console.log('Logging in...');
    
    // Wait for navigation after login
    await page.waitForNavigation({ waitUntil: 'networkidle2', timeout: 30000 });
    
    // Navigate to users page - start with a larger page size to see more users
    console.log('Navigating to users page...');
    await page.goto('https://admin.edapp.com/users?pageSize=100&page=1', { waitUntil: 'networkidle2' });
    
    // Wait for the table to load - look for the actual table element
    console.log('Waiting for users table to load...');
    await page.waitForSelector('table[data-testid="table"]', { timeout: 10000 });
    
    // Wait a bit longer for React to render all the rows
    await new Promise(resolve => setTimeout(resolve, 5000));
    
    // Look for users without green checkmarks (pending users)
    console.log('Checking for pending users...');
    
    // First, let's see what we can find on the page for debugging
    const pageDebug = await page.evaluate(() => {
      return {
        totalRows: document.querySelectorAll('tr[data-testid^="row-"]').length,
        verifiedTrue: document.querySelectorAll('svg[data-testid="verified-true"]').length,
        verifiedFalse: document.querySelectorAll('svg[data-testid="verified-false"]').length,
        optionsButtons: document.querySelectorAll('button[data-testid="user-options-button"]').length
      };
    });
    console.log('Page debug info:', pageDebug);
    
    // Find all user rows with verified-false status (pending approval)
    const pendingUsers = await page.evaluate(() => {
      const users = [];
      // Find all rows in the table
      const rows = document.querySelectorAll('tr[data-testid^="row-"]');
      
      rows.forEach((row) => {
        // Check if this row has a verified-false icon (pending user)
        const verifiedFalse = row.querySelector('svg[data-testid="verified-false"]');
        
        if (verifiedFalse) {
          // Get the user's name from the cell-Name column
          const nameCell = row.querySelector('td[data-testid="cell-Name"]');
          const name = nameCell ? nameCell.textContent.trim() : 'Unknown';
          
          // Get the options button
          const optionsButton = row.querySelector('button[data-testid="user-options-button"]');
          
          if (optionsButton) {
            users.push({ name });
          }
        }
      });
      
      return users;
    });
    
    console.log(`Found ${pendingUsers.length} potential pending users`);
    
    if (pendingUsers.length === 0) {
      results.message = 'No pending users found';
    } else {
      // Approve each pending user
      for (const user of pendingUsers) {
        try {
          console.log(`Approving user: ${user.name}`);
          
          // Find the row again and click its options button
          const clicked = await page.evaluate((userName) => {
            const rows = document.querySelectorAll('tr[data-testid^="row-"]');
            for (const row of rows) {
              const nameCell = row.querySelector('td[data-testid="cell-Name"]');
              if (nameCell && nameCell.textContent.trim() === userName) {
                const button = row.querySelector('button[data-testid="user-options-button"]');
                if (button) {
                  button.click();
                  return true;
                }
              }
            }
            return false;
          }, user.name);
          
          if (!clicked) {
            results.errors.push(`Could not find or click options button for ${user.name}`);
            continue;
          }
          
          // Wait for the menu to appear
          await new Promise(resolve => setTimeout(resolve, 2000));
          
          // Look for and click the "Verify User" option
          console.log('Looking for verify option...');
          await page.waitForSelector('li[data-testid="verify-user-option"]', { timeout: 5000 });
          
          const verifyClicked = await page.evaluate(() => {
            const option = document.querySelector('li[data-testid="verify-user-option"]');
            if (option) {
              option.click();
              return true;
            }
            return false;
          });
          
          if (verifyClicked) {
            console.log('Clicked verify option, waiting for confirmation modal...');
            await new Promise(resolve => setTimeout(resolve, 2000));
            
            // Click the confirmation "Verify" button in the modal
            console.log('Looking for confirmation button...');
            
            const confirmClicked = await page.evaluate(() => {
              // Find the blue "Verify" button in the modal
              const buttons = Array.from(document.querySelectorAll('button'));
              const verifyButton = buttons.find(btn => btn.textContent.trim() === 'Verify');
              if (verifyButton) {
                verifyButton.click();
                return true;
              }
              return false;
            });
            
            if (confirmClicked) {
              console.log('Clicked confirmation button, waiting...');
              await new Promise(resolve => setTimeout(resolve, 3000));
              
              results.approved.push(user.name);
              console.log(`✓ Approved: ${user.name}`);
            } else {
              results.errors.push(`Could not find confirmation button for ${user.name}`);
            }
          } else {
            results.errors.push(`Could not find or click verify option for ${user.name}`);
          }
        } catch (error) {
          results.errors.push(`Error approving ${user.name}: ${error.message}`);
          console.error(`Error approving ${user.name}:`, error);
        }
      }
    }
    
  } catch (error) {
    console.error('Error in approval process:', error);
    results.errors.push(`Main process error: ${error.message}`);
  } finally {
    if (browser) {
      await browser.close();
    }
  }
  
  // ONLY send email if users were actually approved
  // Do NOT send email for "no pending users" or if only checking found nothing
  if (results.approved.length > 0) {
    await sendEmailNotification(results);
  } else {
    console.log('No users were approved - skipping email notification');
    // Still log errors to console but don't email about them unless users were approved
    if (results.errors.length > 0) {
      console.log('Errors occurred:', results.errors);
    }
  }
  
  return results;
}

async function sendEmailNotification(results) {
  try {
    // Create transporter
    const transporter = nodemailer.createTransport({
      service: 'gmail',
      auth: {
        user: process.env.GMAIL_USER,
        pass: process.env.GMAIL_APP_PASSWORD
      }
    });
    
    // Build email content
    let emailBody = `EdApp User Approval Report\n`;
    emailBody += `Time: ${new Date(results.timestamp).toLocaleString()}\n\n`;
    
    if (results.approved.length > 0) {
      emailBody += `✓ APPROVED USERS (${results.approved.length}):\n`;
      results.approved.forEach(name => {
        emailBody += `  • ${name}\n`;
      });
      emailBody += '\n';
    } else {
      emailBody += `No users were approved.\n\n`;
    }
    
    if (results.errors.length > 0) {
      emailBody += `⚠ ERRORS (${results.errors.length}):\n`;
      results.errors.forEach(error => {
        emailBody += `  • ${error}\n`;
      });
      emailBody += '\n';
    }
    
    if (results.message) {
      emailBody += `${results.message}\n`;
    }
    
    const subject = results.approved.length > 0
      ? `✓ EdApp: ${results.approved.length} user(s) approved`
      : 'EdApp: No pending users';
    
    await transporter.sendMail({
      from: process.env.GMAIL_USER,
      to: process.env.NOTIFICATION_EMAIL,
      subject: subject,
      text: emailBody
    });
    
    console.log('Email notification sent successfully');
  } catch (error) {
    console.error('Error sending email:', error);
  }
}

// Run the function
approveEdAppUsers()
  .then(results => {
    console.log('Process completed:', JSON.stringify(results, null, 2));
    process.exit(0);
  })
  .catch(error => {
    console.error('Fatal error:', error);
    process.exit(1);
  });
